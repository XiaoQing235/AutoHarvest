package kite.autoharvest.util;

import kite.autoharvest.config.AutoHarvestConfig;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.InteractionResult;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.Vec3;

public final class InteractionHelper {

    private InteractionHelper() {
    }

    /** Returns whether an interaction was attempted, not whether the server accepted it. */
    public static boolean interactBlock(LocalPlayer player, BlockPos blockPos, InteractionHand hand, Direction side) {
        Minecraft client = Minecraft.getInstance();
        if (client.gameMode == null || player == null || !InteractionRange.canReachBlock(player, blockPos)) return false;
        // Scans borrow a MutableBlockPos; vanilla may retain the interaction target.
        blockPos = blockPos.immutable();
        Vec3 hitPos = Vec3.atCenterOf(blockPos);
        BlockHitResult hitResult = new BlockHitResult(hitPos, side, blockPos, false);
        swingIfNeeded(player, hand, client.gameMode.useItemOn(player, hand, hitResult));
        return true;
    }

    public static boolean breakBlock(BlockPos blockPos, Direction side) {
        Minecraft client = Minecraft.getInstance();
        LocalPlayer player = client.player;
        if (client.gameMode == null || player == null || !InteractionRange.canReachBlock(player, blockPos)) return false;
        blockPos = blockPos.immutable();
        if (client.gameMode.startDestroyBlock(blockPos, side) && AutoHarvestConfig.swingHand()) {
            player.swing(InteractionHand.MAIN_HAND);
        }
        // Failed local attempts still consume the caller's action budget.
        return true;
    }

    public static boolean interactEntity(LocalPlayer player, Entity target, InteractionHand hand) {
        Minecraft client = Minecraft.getInstance();
        if (client.gameMode == null || player == null || target == null || !InteractionRange.canReachEntity(player, target)) return false;
        Vec3 hitLocation = target.getBoundingBox().getCenter();
        EntityHitResult entityHitResult = new EntityHitResult(target, hitLocation);
        swingIfNeeded(player, hand, client.gameMode.interact(player, target, entityHitResult, hand));
        return true;
    }

    public static boolean interactItem(LocalPlayer player, InteractionHand hand) {
        Minecraft client = Minecraft.getInstance();
        if (client.gameMode == null || player == null) return false;
        swingIfNeeded(player, hand, client.gameMode.useItem(player, hand));
        return true;
    }

    private static void swingIfNeeded(LocalPlayer player, InteractionHand hand, InteractionResult result) {
        if (AutoHarvestConfig.swingHand()
                && result instanceof InteractionResult.Success success
                && success.swingSource() == InteractionResult.SwingSource.CLIENT) {
            player.swing(hand);
        }
    }
}
