#!/usr/bin/env python3
"""README: run python3 scripts/test_interactions.py with Java 21+ available.

Compiles only InteractionRange/InteractionHelper against minimal temporary stubs.
No Gradle or Minecraft dependency build is performed. These behavioral regression
checks do NOT verify real Minecraft API compatibility, networking, or runtime
behavior. Config defaults below are fixtures, not a test of Cloth Config wiring.
All generated Java sources/classes are removed when the script exits.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STUBS = {
    'kite.autoharvest.config.AutoHarvestConfig': '''
public class AutoHarvestConfig {
    public static boolean attribute, swing;
    public static double custom = 4.5;
    public static boolean usePlayerRange() { return attribute; }
    public static boolean swingHand() { return swing; }
    public static double radius() { return custom; }
}''',
    'net.minecraft.core.BlockPos': 'public record BlockPos(int x, int y, int z) {}',
    'net.minecraft.core.Direction': 'public enum Direction { UP }',
    'net.minecraft.world.InteractionHand': 'public enum InteractionHand { MAIN_HAND, OFF_HAND }',
    'net.minecraft.world.InteractionResult': '''
public interface InteractionResult {
    enum SwingSource { CLIENT, SERVER, NONE }
    record Success(SwingSource swingSource) implements InteractionResult {}
    record Fail() implements InteractionResult {}
}''',
    'net.minecraft.world.phys.Vec3': '''
public record Vec3(double x, double y, double z) {
    public static Vec3 atCenterOf(net.minecraft.core.BlockPos p) {
        return new Vec3(p.x()+.5, p.y()+.5, p.z()+.5);
    }
}''',
    'net.minecraft.world.phys.AABB': '''
public class AABB { public Vec3 getCenter() { return new Vec3(0, 0, 0); } }''',
    'net.minecraft.world.phys.BlockHitResult': '''
public record BlockHitResult(Vec3 location, net.minecraft.core.Direction side,
    net.minecraft.core.BlockPos pos, boolean inside) {}''',
    'net.minecraft.world.phys.EntityHitResult': '''
public record EntityHitResult(net.minecraft.world.entity.Entity entity, Vec3 location) {}''',
    'net.minecraft.world.entity.Entity': '''
public class Entity {
    public net.minecraft.world.phys.AABB getBoundingBox() { return new net.minecraft.world.phys.AABB(); }
}''',
    'net.minecraft.client.player.LocalPlayer': '''
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.phys.Vec3;
public class LocalPlayer {
    public double blockRange = 5, entityRange = 3, blockBuffer = -1, entityBuffer = -1;
    public boolean blockReach, entityReach;
    public int blockChecks, entityChecks, swings;
    public BlockPos checkedPos;
    public Entity checkedEntity;
    public InteractionHand swungHand;
    public final Vec3 feet = new Vec3(0, 0, 0), eyes = new Vec3(0, 1.62, 0);
    public double blockInteractionRange() { return blockRange; }
    public double entityInteractionRange() { return entityRange; }
    public Vec3 position() { return feet; }
    public Vec3 getEyePosition() { return eyes; }
    public boolean isWithinBlockInteractionRange(BlockPos pos, double buffer) {
        blockChecks++; checkedPos = pos; blockBuffer = buffer; return blockReach;
    }
    public boolean isWithinEntityInteractionRange(Entity entity, double buffer) {
        entityChecks++; checkedEntity = entity; entityBuffer = buffer; return entityReach;
    }
    public void swing(InteractionHand hand) { swings++; swungHand = hand; }
}''',
    'net.minecraft.client.Minecraft': '''
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.*;
import net.minecraft.world.*;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.*;
public class Minecraft {
    private static final Minecraft INSTANCE = new Minecraft();
    public static Minecraft getInstance() { return INSTANCE; }
    public LocalPlayer player;
    public GameMode gameMode = new GameMode();
    public static class GameMode {
        public int calls;
        public boolean breakAccepted;
        public InteractionHand usedHand;
        public InteractionResult result = new InteractionResult.Fail();
        private InteractionResult use(InteractionHand hand) { calls++; usedHand=hand; return result; }
        public InteractionResult useItemOn(LocalPlayer p, InteractionHand h, BlockHitResult hit) { return use(h); }
        public InteractionResult useItem(LocalPlayer p, InteractionHand h) { return use(h); }
        public InteractionResult interact(LocalPlayer p, Entity e, EntityHitResult hit, InteractionHand h) { return use(h); }
        public boolean startDestroyBlock(BlockPos pos, Direction side) { calls++; return breakAccepted; }
    }
}''',
}
TEST = '''
import kite.autoharvest.config.AutoHarvestConfig;
import kite.autoharvest.util.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.*;
import net.minecraft.world.*;
import net.minecraft.world.entity.Entity;

public class InteractionTests {
    static int assertions;
    static void check(boolean condition, String name) {
        assertions++;
        if (!condition) throw new AssertionError(name);
    }
    public static void main(String[] args) {
        LocalPlayer p = new LocalPlayer();
        Entity entity = new Entity();
        BlockPos pos = new BlockPos(99, 0, 0);
        Minecraft mc = Minecraft.getInstance();
        mc.player = p;
        var gm = mc.gameMode;
        var off = InteractionHand.OFF_HAND;
        check(InteractionRange.blockRadius(p) == 4.5, "default custom radius");
        check(InteractionRange.scanCenter(p) == p.feet, "legacy feet origin");
        AutoHarvestConfig.custom = 300;
        check(InteractionRange.blockRadius(p) == 300 && InteractionRange.entityRadius(p) == 300,
            "custom radius has no hidden clamp");
        check(InteractionRange.blockScanRadius(p) == 300, "custom scan unchanged");
        check(InteractionRange.canReachBlock(p, pos) && InteractionRange.canReachEntity(p, entity),
            "custom mode preserves caller filtering and adjacent base interactions");
        check(p.blockChecks == 0 && p.entityChecks == 0, "custom skips vanilla guards");
        AutoHarvestConfig.attribute = true;
        check(InteractionRange.blockRadius(p) == 5 && InteractionRange.entityRadius(p) == 3,
            "separate block and entity attributes");
        p.blockRange = 100; p.entityRange = 80;
        check(InteractionRange.blockRadius(p) == 100 && InteractionRange.entityRadius(p) == 80,
            "attributes are dynamic and unclamped");
        check(InteractionRange.blockScanRadius(p) > 100, "broad phase includes block box and adjacent targets");
        check(InteractionRange.scanCenter(p) == p.eyes, "attribute eye origin");
        check(!InteractionHelper.interactBlock(p, pos, off, Direction.UP), "block rejected");
        check(!InteractionHelper.breakBlock(pos, Direction.UP), "break rejected");
        check(!InteractionHelper.interactEntity(p, entity, off), "entity rejected");
        check(gm.calls == 0, "range rejection precedes dispatch");
        check(p.checkedPos == pos && p.checkedEntity == entity && p.blockBuffer == 0 && p.entityBuffer == 0,
            "vanilla guards receive actual targets and zero buffer");
        p.blockReach = p.entityReach = true;
        check(InteractionHelper.interactBlock(p, pos, off, Direction.UP), "failed result still counts block attempt");
        check(InteractionHelper.interactEntity(p, entity, off), "failed result still counts entity attempt");
        check(InteractionHelper.interactItem(p, off), "failed result still counts item attempt");
        check(InteractionHelper.breakBlock(pos, Direction.UP), "rejected destruction still counts attempt");
        check(gm.calls == 4 && p.swings == 0, "attempt count and disabled swing");
        gm.result = new InteractionResult.Success(InteractionResult.SwingSource.CLIENT);
        gm.breakAccepted = true;
        InteractionHelper.interactBlock(p, pos, off, Direction.UP);
        InteractionHelper.interactEntity(p, entity, off);
        InteractionHelper.interactItem(p, off);
        InteractionHelper.breakBlock(pos, Direction.UP);
        check(p.swings == 0, "disabled swing suppresses successful client swings");
        AutoHarvestConfig.swing = true;
        InteractionHelper.interactBlock(p, pos, off, Direction.UP);
        check(p.swings == 1 && p.swungHand == off && gm.usedHand == off, "block swings actual offhand");
        InteractionHelper.interactEntity(p, entity, off);
        check(p.swings == 2 && p.swungHand == off, "entity client success swings offhand");
        InteractionHelper.interactItem(p, off);
        check(p.swings == 3 && p.swungHand == off, "item client success swings offhand");
        for (InteractionResult result : new InteractionResult[] {
                new InteractionResult.Success(InteractionResult.SwingSource.SERVER),
                new InteractionResult.Success(InteractionResult.SwingSource.NONE), new InteractionResult.Fail() }) {
            gm.result = result;
            InteractionHelper.interactBlock(p, pos, off, Direction.UP);
            InteractionHelper.interactEntity(p, entity, off);
            InteractionHelper.interactItem(p, off);
            check(p.swings == 3, "only CLIENT success causes extra swing: " + result);
        }
        gm.breakAccepted = false;
        check(InteractionHelper.breakBlock(pos, Direction.UP) && p.swings == 3, "failed break no swing");
        gm.breakAccepted = true;
        check(InteractionHelper.breakBlock(pos, Direction.UP), "accepted break dispatched");
        check(p.swings == 4 && p.swungHand == InteractionHand.MAIN_HAND, "accepted break main-hand swing");
        int calls = gm.calls;
        p.blockReach = p.entityReach = false;
        check(!InteractionHelper.interactBlock(p, pos, off, Direction.UP)
            && !InteractionHelper.interactEntity(p, entity, off) && gm.calls == calls,
            "reach rechecked after attribute/target change");
        check(!InteractionHelper.interactItem(null, off)
            && !InteractionHelper.interactEntity(p, null, off), "null arguments rejected");
        mc.player = null;
        check(!InteractionHelper.breakBlock(pos, Direction.UP), "missing player rejected");
        mc.gameMode = null;
        check(!InteractionHelper.interactBlock(p, pos, off, Direction.UP)
            && !InteractionHelper.interactEntity(p, entity, off)
            && !InteractionHelper.interactItem(p, off), "missing game mode rejected");
        System.out.println("PASS: " + assertions + " interaction assertions (stub APIs only)");
    }
}
'''


def main():
    java = shutil.which('java')
    if not java:
        raise SystemExit('Java 21+ is required.')
    javac = shutil.which('javac')
    compiler = [javac] if javac else [java, 'com.sun.tools.javac.Main']
    with tempfile.TemporaryDirectory(prefix='autoharvest-interaction-tests-') as temporary:
        base = Path(temporary)
        sources = []
        for name, body in STUBS.items():
            package, _, classname = name.rpartition('.')
            path = base / (name.replace('.', '/') + '.java')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'package {package};\n{body}\n')
            sources.append(str(path))
        for name in ('InteractionRange', 'InteractionHelper'):
            source = ROOT / f'common/src/main/java/kite/autoharvest/util/{name}.java'
            target = base / f'kite/autoharvest/util/{name}.java'
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            sources.append(str(target))
        harness = base / 'InteractionTests.java'
        harness.write_text(TEST)
        sources.append(str(harness))
        classes = base / 'classes'
        subprocess.run(compiler + ['-source', '21', '-target', '21', '-d', str(classes)] + sources, check=True)
        subprocess.run([java, '-cp', str(classes), 'InteractionTests'], check=True)


if __name__ == '__main__':
    main()
