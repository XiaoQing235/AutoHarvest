package kite.autoharvest.util;

import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.tags.BlockTags;
import net.minecraft.tags.FluidTags;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.state.properties.BlockStateProperties;

public final class WaterProximityChecker {

    private WaterProximityChecker() {
    }

    private static final Direction[] HORIZONTAL_DIRECTIONS = {
            Direction.NORTH,
            Direction.SOUTH,
            Direction.WEST,
            Direction.EAST
    };

    public static boolean isAdjacentToSourceWaterHorizontally(Level world, BlockPos pos) {
        for (Direction dir : HORIZONTAL_DIRECTIONS) {
            BlockPos offsetPos = pos.relative(dir);
            var state = world.getBlockState(offsetPos);
            var fluidState = state.getFluidState();
            if (fluidState.is(FluidTags.SUPPORTS_SUGAR_CANE_ADJACENTLY)
                    || state.is(BlockTags.SUPPORTS_SUGAR_CANE_ADJACENTLY)) {
                return true;
            }
        }
        return false;
    }

    // Vanilla farmland accepts both source and flowing water in this 9 x 2 x 9 region.
    public static boolean hasNoWaterNearby(Level world, BlockPos pos) {
        BlockPos.MutableBlockPos checkPos = new BlockPos.MutableBlockPos();
        for (int dy = 0; dy <= 1; dy++) {
            for (int dx = -4; dx <= 4; dx++) {
                for (int dz = -4; dz <= 4; dz++) {
                    checkPos.set(pos.getX() + dx, pos.getY() + dy, pos.getZ() + dz);
                    var state = world.getBlockState(checkPos);
                    var fluidState = state.getFluidState();
                    if (fluidState.is(FluidTags.WATER)) {
                        return false;
                    }
                    if (state.hasProperty(BlockStateProperties.WATERLOGGED) && state.getValue(BlockStateProperties.WATERLOGGED)) {
                        return false;
                    }
                }
            }
        }
        return true;
    }
}
