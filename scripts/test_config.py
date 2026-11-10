#!/usr/bin/env python3
"""Run: python3 scripts/test_config.py /path/to/gson.jar (JDK 21+).

Tests the real config, field adapter and range helper with real Gson. Only Cloth
and Minecraft APIs are stubbed; this does not build the mod or launch its GUI.
Uses an existing Gson JAR, never invokes Gradle or downloads dependencies.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
from test_interactions import STUBS as INTERACTION_STUBS

ROOT = Path(__file__).resolve().parents[1]
STUBS = dict(INTERACTION_STUBS)
del STUBS['kite.autoharvest.config.AutoHarvestConfig']
STUBS.update({
    'kite.autoharvest.config.ModeEnum': 'public enum ModeEnum { plant, harvest }',
    'me.shedaniel.autoconfig.ConfigData': 'public interface ConfigData {}',
    'me.shedaniel.autoconfig.AutoConfig': '''
public class AutoConfig {
    public static Object current;
    public record Holder<T>(Class<T> type) {
        public T getConfig() { return type.cast(current); }
        public void save() {}
    }
    public static <T> Holder<T> getConfigHolder(Class<T> type) { return new Holder<>(type); }
}
''',
    'me.shedaniel.autoconfig.annotation.Config': '''
public @interface Config { String name(); }
''',
    'me.shedaniel.autoconfig.annotation.ConfigEntry': '''
public @interface ConfigEntry {
    @interface BoundedDiscrete { long min(); long max(); }
    @interface Gui {
        @java.lang.annotation.Retention(java.lang.annotation.RetentionPolicy.RUNTIME)
        @interface Tooltip {}
        @java.lang.annotation.Retention(java.lang.annotation.RetentionPolicy.RUNTIME)
        @interface EnumHandler {}
    }
}
''',
})

TEST = r'''
import com.google.gson.*;
import com.google.gson.annotations.JsonAdapter;
import kite.autoharvest.config.*;
import kite.autoharvest.util.InteractionRange;
import me.shedaniel.autoconfig.AutoConfig;
import me.shedaniel.autoconfig.annotation.ConfigEntry;
import net.minecraft.client.player.LocalPlayer;

public class ConfigTests {
    private static int assertions;
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();

    private static void check(boolean condition, String message) {
        assertions++;
        if (!condition) throw new AssertionError(message);
    }

    private static void roundTrip(String input, boolean expected, int radius) {
        AutoHarvestConfig config = GSON.fromJson(input, AutoHarvestConfig.class);
        AutoConfig.current = config;
        check(config.rangeSource == expected, "read source: " + input);
        check(AutoHarvestConfig.usePlayerRange() == expected, "live accessor");
        check(config.radiusCenti == radius, "preserve configured radius");
        check(config.maxActionsPerTick == 7 && config.swingHand, "preserve other fields");

        LocalPlayer player = new LocalPlayer();
        player.blockRange = 12;
        player.entityRange = 8;
        check(InteractionRange.blockRadius(player) == (expected ? 12 : radius / 10.0),
                "block distance source");
        check(InteractionRange.entityRadius(player) == (expected ? 8 : radius / 10.0),
                "entity distance source");
        config.rangeSource = !expected;
        check(AutoHarvestConfig.usePlayerRange() == !expected, "toggle applies immediately");
        check(InteractionRange.blockRadius(player) == (!expected ? 12 : radius / 10.0),
                "toggled block source");
        config.rangeSource = expected;

        JsonObject saved = GSON.toJsonTree(config).getAsJsonObject();
        check(saved.getAsJsonPrimitive("rangeSource").isBoolean(), "save boolean, not enum text");
        check(saved.get("rangeSource").getAsBoolean() == expected, "save selected state");
        check(saved.get("radiusCenti").getAsInt() == radius, "save radius unchanged");
        AutoHarvestConfig reloaded = GSON.fromJson(saved, AutoHarvestConfig.class);
        check(reloaded.rangeSource == expected, "reload migrated boolean");
        check(reloaded.maxActionsPerTick == 7 && reloaded.swingHand, "reload other fields");
    }

    public static void main(String[] args) throws Exception {
        var field = AutoHarvestConfig.class.getField("rangeSource");
        check(field.getType() == boolean.class, "GUI must receive primitive boolean");
        check(!field.isAnnotationPresent(ConfigEntry.Gui.EnumHandler.class), "no enum dropdown");
        check(field.isAnnotationPresent(ConfigEntry.Gui.Tooltip.class), "GUI explanation retained");
        check(field.getAnnotation(JsonAdapter.class).value() == RangeSourceAdapter.class,
                "migration adapter wired to real field");
        AutoHarvestConfig defaults = GSON.fromJson("{}", AutoHarvestConfig.class);
        check(!defaults.rangeSource && defaults.radiusCenti == 45, "existing defaults retained");

        String suffix = "\"radiusCenti\":63,\"maxActionsPerTick\":7,\"swingHand\":true}";
        roundTrip("{" + suffix, false, 63);
        roundTrip("{\"rangeSource\":false," + suffix, false, 63);
        roundTrip("{\"rangeSource\":true," + suffix, true, 63);
        roundTrip("{\"rangeSource\":\"CUSTOM\"," + suffix, false, 63);
        roundTrip("{\"rangeSource\":\"PLAYER_ATTRIBUTE\"," + suffix, true, 63);
        roundTrip("{\"rangeSource\":null," + suffix, false, 63);
        roundTrip("{\"rangeSource\":\"unknown\"," + suffix, false, 63);
        roundTrip("{\"rangeSource\":\"true\"," + suffix, true, 63);
        roundTrip("{\"rangeSource\":\"false\"," + suffix, false, 63);
        roundTrip("{\"rangeSource\":{}," + suffix, false, 63);
        System.out.println("PASS: " + assertions + " config assertions (real Gson; Cloth/Minecraft stubs)");
    }
}
'''


def main():
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_file():
        raise SystemExit('Usage: python3 scripts/test_config.py /path/to/gson.jar')
    gson = str(Path(sys.argv[1]).resolve())
    java = shutil.which('java')
    if not java:
        raise SystemExit('Java 21+ is required.')
    javac = shutil.which('javac')
    compiler = [javac] if javac else [java, 'com.sun.tools.javac.Main']
    with tempfile.TemporaryDirectory(prefix='autoharvest-config-tests-') as temporary:
        base = Path(temporary)
        sources = []
        for name, body in STUBS.items():
            package, _, _ = name.rpartition('.')
            path = base / (name.replace('.', '/') + '.java')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'package {package};\n{body}\n')
            sources.append(str(path))
        for relative in ('config/AutoHarvestConfig', 'config/RangeSourceAdapter', 'util/InteractionRange'):
            source = ROOT / f'common/src/main/java/kite/autoharvest/{relative}.java'
            target = base / f'kite/autoharvest/{relative}.java'
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            sources.append(str(target))
        harness = base / 'ConfigTests.java'
        harness.write_text(TEST)
        sources.append(str(harness))
        classes = base / 'classes'
        subprocess.run(compiler + ['-source', '21', '-target', '21', '-cp', gson,
                                  '-d', str(classes)] + sources, check=True)
        subprocess.run([java, '-cp', str(classes) + os.pathsep + gson, 'ConfigTests'], check=True)


if __name__ == '__main__':
    main()
