#!/usr/bin/env python3
"""README: run python3 scripts/test_water.py with Java 21+.

Tests production WaterProximityChecker against temporary minimal Minecraft stubs.
Does not run Gradle, build Minecraft dependencies, or verify real Minecraft API
compatibility/runtime behavior. Generated sources/classes are always cleaned up.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
STUBS = {
    'net.minecraft.core.Direction': '''
public enum Direction {
    NORTH(0,0,-1), SOUTH(0,0,1), WEST(-1,0,0), EAST(1,0,0);
    public final int x,y,z;
    Direction(int x,int y,int z) { this.x=x; this.y=y; this.z=z; }
}''',
    'net.minecraft.core.BlockPos': '''
public class BlockPos {
    protected int x,y,z;
    public BlockPos(int x,int y,int z) { this.x=x; this.y=y; this.z=z; }
    public int getX() { return x; }
    public int getY() { return y; }
    public int getZ() { return z; }
    public BlockPos relative(Direction d) { return new BlockPos(x+d.x,y+d.y,z+d.z); }
    public static class MutableBlockPos extends BlockPos {
        public MutableBlockPos() { super(0,0,0); }
        public MutableBlockPos set(int x,int y,int z) { this.x=x; this.y=y; this.z=z; return this; }
    }
}''',
    'net.minecraft.tags.FluidTags': 'public class FluidTags { public static final Object WATER = new Object(); }',
    'net.minecraft.world.level.block.Blocks': '''
public class Blocks {
    public static final Object WATER = new Object(), AIR = new Object(), SOLID = new Object();
}''',
    'net.minecraft.world.level.block.state.properties.BlockStateProperties': '''
public class BlockStateProperties { public static final Object WATERLOGGED = new Object(); }''',
    'net.minecraft.world.level.material.FluidState': '''
public record FluidState(boolean water, boolean source) {
    public boolean is(Object tag) { return water && tag == net.minecraft.tags.FluidTags.WATER; }
    public boolean isSource() { return source; }
}''',
    'net.minecraft.world.level.block.state.BlockState': '''
import net.minecraft.world.level.material.FluidState;
public record BlockState(Object block, FluidState fluid, boolean waterlogProperty, boolean waterlogged) {
    public Object getBlock() { return block; }
    public FluidState getFluidState() { return fluid; }
    public boolean hasProperty(Object property) { return waterlogProperty; }
    public boolean getValue(Object property) { return waterlogged; }
}''',
    'net.minecraft.world.level.Level': '''
import java.util.*;
import net.minecraft.core.BlockPos;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.material.FluidState;
public class Level {
    private final Map<String, BlockState> states = new HashMap<>();
    public final Set<String> visited = new HashSet<>();
    public final Set<BlockPos> queriedObjects = Collections.newSetFromMap(new IdentityHashMap<>());
    public int reads;
    private static final BlockState AIR = new BlockState(Blocks.AIR, new FluidState(false,false),false,false);
    public void put(int x,int y,int z,BlockState state) { states.put(x+","+y+","+z,state); }
    public BlockState getBlockState(BlockPos p) {
        reads++; queriedObjects.add(p);
        String key=p.getX()+","+p.getY()+","+p.getZ();
        visited.add(key); return states.getOrDefault(key,AIR);
    }
}''',
}
TEST = '''
import kite.autoharvest.util.WaterProximityChecker;
import net.minecraft.core.*;
import net.minecraft.world.level.Level;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.material.FluidState;
public class WaterTests {
    static int assertions;
    static final BlockPos ORIGIN = new BlockPos(13,64,-27);
    static final BlockState SOURCE = new BlockState(Blocks.WATER,new FluidState(true,true),false,false);
    static final BlockState FLOWING = new BlockState(Blocks.WATER,new FluidState(true,false),false,false);
    static final BlockState LOGGED = new BlockState(Blocks.SOLID,new FluidState(false,false),true,true);
    static final BlockState DRY_LOGGABLE = new BlockState(Blocks.SOLID,new FluidState(false,false),true,false);
    static final BlockState OTHER_FLUID = new BlockState(Blocks.SOLID,new FluidState(false,true),false,false);
    static void check(boolean ok,String name) { assertions++; if(!ok) throw new AssertionError(name); }
    static Level world(int x,int y,int z,BlockState state) {
        Level world=new Level(); world.put(ORIGIN.getX()+x,ORIGIN.getY()+y,ORIGIN.getZ()+z,state); return world;
    }
    public static void main(String[] args) {
        Level empty=new Level();
        check(WaterProximityChecker.hasNoWaterNearby(empty,ORIGIN),"dry world");
        check(empty.reads==162 && empty.visited.size()==162,"exact 9 x 2 x 9 scan");
        check(empty.queriedObjects.size()==1,"reuse one mutable block position");
        // Exhaust every inclusive scan position, including all corners and both height layers.
        for(int x=-4;x<=4;x++) for(int z=-4;z<=4;z++) for(int y=0;y<=1;y++) {
            check(!WaterProximityChecker.hasNoWaterNearby(world(x,y,z,SOURCE),ORIGIN),
                "source inside scan: "+x+","+y+","+z);
        }
        for(int[] xyz:new int[][] {{-5,0,0},{5,1,0},{0,0,-5},{0,1,5},{0,-1,0},{0,2,0},
                {-5,1,-4},{4,0,5}}) {
            check(WaterProximityChecker.hasNoWaterNearby(world(xyz[0],xyz[1],xyz[2],SOURCE),ORIGIN),
                "source outside scan: "+java.util.Arrays.toString(xyz));
        }
        for(int y=0;y<=1;y++) {
            check(WaterProximityChecker.hasNoWaterNearby(world(0,y,0,FLOWING),ORIGIN),"flowing ignored");
            check(!WaterProximityChecker.hasNoWaterNearby(world(4,y,-4,LOGGED),ORIGIN),"waterlogged accepted");
            check(WaterProximityChecker.hasNoWaterNearby(world(0,y,0,DRY_LOGGABLE),ORIGIN),"dry waterloggable ignored");
            check(WaterProximityChecker.hasNoWaterNearby(world(0,y,0,OTHER_FLUID),ORIGIN),"other source fluid ignored");
        }
        check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(new Level(),ORIGIN),"no adjacent water");
        for(int[] xyz:new int[][] {{1,0,0},{-1,0,0},{0,0,1},{0,0,-1}}) {
            int x=xyz[0],y=xyz[1],z=xyz[2];
            check(WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,SOURCE),ORIGIN),"adjacent source accepted");
            check(WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,LOGGED),ORIGIN),"adjacent logged accepted");
            check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,FLOWING),ORIGIN),"adjacent flowing ignored");
            check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,DRY_LOGGABLE),ORIGIN),"adjacent dry ignored");
            check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,OTHER_FLUID),ORIGIN),"adjacent other fluid ignored");
        }
        for(int[] xyz:new int[][] {{0,1,0},{0,-1,0},{1,1,0},{1,-1,0},{1,0,1},{2,0,0},{0,0,0}}) {
            for(BlockState state:new BlockState[] {SOURCE,LOGGED})
                check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(xyz[0],xyz[1],xyz[2],state),ORIGIN),
                    "non-horizontal-neighbor ignored: "+java.util.Arrays.toString(xyz));
        }
        System.out.println("PASS: "+assertions+" water assertions (stub APIs only)");
    }
}
'''


def main():
    java = shutil.which('java')
    if not java:
        raise SystemExit('Java 21+ is required.')
    javac = shutil.which('javac')
    compiler = [javac] if javac else [java, 'com.sun.tools.javac.Main']
    with tempfile.TemporaryDirectory(prefix='autoharvest-water-tests-') as temporary:
        base = Path(temporary)
        sources = []
        for name, body in STUBS.items():
            package = name.rpartition('.')[0]
            path = base / (name.replace('.', '/') + '.java')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'package {package};\n{body}\n')
            sources.append(str(path))
        source = ROOT / 'common/src/main/java/kite/autoharvest/util/WaterProximityChecker.java'
        target = base / 'kite/autoharvest/util/WaterProximityChecker.java'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        harness = base / 'WaterTests.java'
        harness.write_text(TEST)
        sources.extend([str(target), str(harness)])
        classes = base / 'classes'
        subprocess.run(compiler + ['-source', '21', '-target', '21', '-d', str(classes)] + sources, check=True)
        subprocess.run([java, '-cp', str(classes), 'WaterTests'], check=True)


if __name__ == '__main__':
    main()
