package kite.autoharvest.util;

import kite.autoharvest.config.AutoHarvestConfig;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.Vec3;

/** Separates the legacy scan radius from vanilla attribute-based interaction reach. */
public final class InteractionRange {
    private InteractionRange() {
    }

    public static double blockRadius(LocalPlayer player) {
        return AutoHarvestConfig.usePlayerRange() ? player.blockInteractionRange() : AutoHarvestConfig.radius();
    }

    /** Broad phase only: include reachable block boxes and adjacent planting/harvest targets. */
    public static double blockScanRadius(LocalPlayer player) {
        double radius = blockRadius(player);
        return AutoHarvestConfig.usePlayerRange() ? radius + 1.0 + Math.sqrt(3.0) / 2.0 : radius;
    }

    public static double entityRadius(LocalPlayer player) {
        return AutoHarvestConfig.usePlayerRange() ? player.entityInteractionRange() : AutoHarvestConfig.radius();
    }

    public static Vec3 scanCenter(LocalPlayer player) {
        return AutoHarvestConfig.usePlayerRange() ? player.getEyePosition() : player.position();
    }

    /**
     * In custom mode, callers retain their existing feet-to-block-center scan filter.
     * Do not filter the execution position again: planting may interact with an adjacent base.
     */
    public static boolean canReachBlock(LocalPlayer player, BlockPos pos) {
        return !AutoHarvestConfig.usePlayerRange() || player.isWithinBlockInteractionRange(pos, 0.0);
    }

    /** Custom mode retains the caller's existing entity search box. */
    public static boolean canReachEntity(LocalPlayer player, Entity entity) {
        return !AutoHarvestConfig.usePlayerRange() || player.isWithinEntityInteractionRange(entity, 0.0);
    }
}
