package kite.autoharvest.util;

import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.util.function.Predicate;
import java.util.Iterator;

public class BoxUtil {

    public static Vec3 getPlayerPos() {
        LocalPlayer player = Minecraft.getInstance().player;
        if (player == null) return null;
        return player.position();
    }

    public static ClientLevel getWorld() {
        return Minecraft.getInstance().level;
    }

    public static LocalPlayer getPlayer() {
        return Minecraft.getInstance().player;
    }

    public static AABB createSearchBox(Vec3 center, double radius) {
        return new AABB(
                center.x - radius, center.y - radius, center.z - radius,
                center.x + radius, center.y + radius, center.z + radius
        );
    }

    public static boolean isOutsideSphere(BlockPos pos, Vec3 center, double radius) {
        double dx = pos.getX() + 0.5 - center.x;
        double dy = pos.getY() + 0.5 - center.y;
        double dz = pos.getZ() + 0.5 - center.z;
        return dx * dx + dy * dy + dz * dz >= radius * radius;
    }

    // Bound raw cube visits, not just in-sphere callbacks, so large attributes cannot freeze a tick.
    public static final int MAX_BLOCKS_PER_SCAN = 4096;

    public static final class ScanCursor {
        private BlockPos origin;
        private double radius;
        private Iterator<BlockPos> iterator;
        private Object world;

        public void reset() {
            origin = null;
            iterator = null;
            world = null;
        }
    }

    public static void forEachBlockInRange(Vec3 center, double radius, Predicate<BlockPos> action) {
        forEachBlockInRange(center, radius, new ScanCursor(), action);
    }

    private static double originDistanceSquared(BlockPos first, BlockPos second) {
        double dx = (double) first.getX() - second.getX();
        double dy = (double) first.getY() - second.getY();
        double dz = (double) first.getZ() - second.getZ();
        return dx * dx + dy * dy + dz * dz;
    }

    /** Callback positions are borrowed mutable positions; call immutable() before retaining one. */
    public static void forEachBlockInRange(Vec3 center, double radius, ScanCursor cursor, Predicate<BlockPos> action) {
        if (!Double.isFinite(radius) || radius <= 0.0 || radius > Integer.MAX_VALUE / 6.0) {
            cursor.reset();
            return;
        }
        BlockPos origin = BlockPos.containing(center);
        int radiusInt = (int) Math.ceil(radius);
        double diameter = 2.0 * radiusInt + 1.0;
        boolean incremental = diameter * diameter * diameter > MAX_BLOCKS_PER_SCAN;
        Object world = getWorld();
        // Keep an anchored sweep while walking, filtering against the live center below.
        // Restarting on every block crossed starves distant targets at large reach.
        // A displacement over the diameter has no overlapping selection sphere.
        boolean relocated = cursor.origin != null && originDistanceSquared(origin, cursor.origin) > 4.0 * radius * radius;
        if (!incremental || cursor.iterator == null || relocated
                || radius != cursor.radius || cursor.world != world) {
            cursor.origin = origin;
            cursor.radius = radius;
            cursor.world = world;
            cursor.iterator = BlockPos.withinManhattan(origin, radiusInt, radiusInt, radiusInt).iterator();
        }
        int visited = 0;
        while (visited < MAX_BLOCKS_PER_SCAN && cursor.iterator.hasNext()) {
            BlockPos pos = cursor.iterator.next();
            visited++;
            if (isOutsideSphere(pos, center, radius)) continue;
            if (action.test(pos)) return;
        }
        if (!cursor.iterator.hasNext()) cursor.reset();
    }
}
