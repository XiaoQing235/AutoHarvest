package kite.autoharvest.util;

import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.function.Predicate;

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

    // Bound all three phases together, including raw cube visits outside the sphere.
    public static final int MAX_BLOCKS_PER_SCAN = 4096;
    private static final int MAX_REMEMBERED_TARGETS = 256;
    private static final int LOCAL_RADIUS = 3;
    private static final int LOCAL_SCAN_SIZE = 343; // (2 * LOCAL_RADIUS + 1)^3

    public static final class ScanCursor {
        private BlockPos origin;
        private double radius;
        private Iterator<BlockPos> iterator;
        private Iterator<BlockPos> localIterator;
        private BlockPos localOrigin;
        private Object world;
        private long invocation;
        private final ArrayDeque<Target> targets = new ArrayDeque<>();
        private final Map<BlockPos, Target> targetsByPos = new HashMap<>();
        private final Set<BlockPos> attempted = new HashSet<>();

        private static final class Target {
            private final BlockPos pos;
            private long lastAttempt;

            private Target(BlockPos pos, long invocation) {
                this.pos = pos;
                this.lastAttempt = invocation;
            }
        }

        /** Retain an attempted/deferred scan position, not an adjacent execution position. */
        public void rememberTarget(BlockPos pos) {
            Target target = targetsByPos.get(pos);
            if (target != null) {
                target.lastAttempt = invocation;
                attempted.add(target.pos);
                return;
            }
            if (targets.size() == MAX_REMEMBERED_TARGETS) {
                targetsByPos.remove(targets.removeFirst().pos);
            }
            target = new Target(pos.immutable(), invocation);
            targets.addLast(target);
            targetsByPos.put(target.pos, target);
            attempted.add(target.pos);
        }

        private boolean attemptedThisInvocation(BlockPos pos) {
            return attempted.contains(pos);
        }

        public void reset() {
            origin = null;
            iterator = null;
            localIterator = null;
            localOrigin = null;
            world = null;
            targets.clear();
            targetsByPos.clear();
            attempted.clear();
        }

        private void startSweep(BlockPos origin, int radiusInt) {
            this.origin = origin;
            iterator = BlockPos.withinManhattan(origin, radiusInt, radiusInt, radiusInt).iterator();
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
        double volume = diameter * diameter * diameter;
        boolean large = volume > MAX_BLOCKS_PER_SCAN;
        Object world = getWorld();
        boolean relocated = cursor.origin != null && originDistanceSquared(origin, cursor.origin) > 4.0 * radius * radius;
        if (cursor.iterator == null || relocated || radius != cursor.radius || cursor.world != world) {
            cursor.reset();
            cursor.radius = radius;
            cursor.world = world;
            cursor.startSweep(origin, radiusInt);
        }
        cursor.invocation++;
        cursor.attempted.clear();

        // Discovery always goes first. Repeated/denied targets cannot monopolize the
        // budget forever: the sweep resumes AFTER them, even at ordinary radii.
        // Reserve bounded work for remembered targets and new targets near a moving
        // player, rather than waiting for a large sweep's empty outer shells.
        int sweepBudget = (int) Math.min(volume, MAX_BLOCKS_PER_SCAN
                - MAX_REMEMBERED_TARGETS - (large ? LOCAL_SCAN_SIZE : 0));
        for (int visited = 0; visited < sweepBudget; visited++) {
            if (!cursor.iterator.hasNext()) {
                cursor.startSweep(origin, radiusInt);
                // Wrap in this invocation, rather than inserting an idle tick.
                // On movement the cubes may overlap; remembered attempts below
                // prevent dispatching twice to those overlapping scan positions.
            }
            BlockPos pos = cursor.iterator.next();
            if (!isOutsideSphere(pos, center, radius)
                    && !cursor.attemptedThisInvocation(pos) && action.test(pos)) return;
        }

        // Discover new nearby work before retrying remembered targets. The local
        // cursor also resumes after actions. Already remembered targets are left
        // to the round-robin retry phase, rather than starving farther retries.
        // Moving recenters ONLY this small pass.
        if (large) {
            if (!origin.equals(cursor.localOrigin)) {
                cursor.localOrigin = origin;
                cursor.localIterator = null;
            }
            for (int visited = 0; visited < LOCAL_SCAN_SIZE; visited++) {
                if (cursor.localIterator == null || !cursor.localIterator.hasNext()) {
                    cursor.localIterator = BlockPos.withinManhattan(origin,
                            LOCAL_RADIUS, LOCAL_RADIUS, LOCAL_RADIUS).iterator();
                }
                BlockPos pos = cursor.localIterator.next();
                if (!isOutsideSphere(pos, center, radius)
                        && !cursor.targetsByPos.containsKey(pos)
                        && !cursor.attemptedThisInvocation(pos) && action.test(pos)) return;
            }
        }

        // Round-robin remembered targets are revalidated through the same callback.
        // Dropping invalid targets also prevents retaining stale world state.
        int remembered = cursor.targets.size();
        for (int i = 0; i < remembered; i++) {
            ScanCursor.Target target = cursor.targets.removeFirst();
            if (target.lastAttempt == cursor.invocation) {
                cursor.targets.addLast(target);
                continue;
            }
            boolean stop = !isOutsideSphere(target.pos, center, radius) && action.test(target.pos);
            if (target.lastAttempt == cursor.invocation) {
                cursor.targets.addLast(target);
            } else {
                cursor.targetsByPos.remove(target.pos);
            }
            if (stop) return;
        }
    }
}
