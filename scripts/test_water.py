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
    'net.minecraft.tags.FluidTags': '''
public class FluidTags {
    public static final Object WATER = new Object(), SUPPORTS_SUGAR_CANE_ADJACENTLY = new Object();
}''',
    'net.minecraft.tags.BlockTags': '''
public class BlockTags { public static final Object SUPPORTS_SUGAR_CANE_ADJACENTLY = new Object(); }''',
    'net.minecraft.world.level.block.Blocks': '''
import java.util.*;
public class Blocks {
    public static final Object WATER = new Object(), AIR = new Object(), SOLID = new Object();
    public static final Object FROSTED_ICE = new Object(), ICE = new Object();
    public static final Set<Object> SUGAR_CANE_SUPPORT = new HashSet<>(Set.of(FROSTED_ICE));
}''',
    'net.minecraft.world.level.block.state.properties.BlockStateProperties': '''
public class BlockStateProperties { public static final Object WATERLOGGED = new Object(); }''',
    'net.minecraft.world.level.material.FluidState': '''
import net.minecraft.tags.FluidTags;
public record FluidState(boolean water, boolean source, boolean sugarCaneSupport) {
    public FluidState(boolean water, boolean source) { this(water,source,water); }
    public boolean is(Object tag) {
        return (water && tag == FluidTags.WATER)
            || (sugarCaneSupport && tag == FluidTags.SUPPORTS_SUGAR_CANE_ADJACENTLY);
    }
    public boolean isSource() { return source; }
}''',
    'net.minecraft.world.level.block.state.BlockState': '''
import net.minecraft.world.level.material.FluidState;
public record BlockState(Object block, FluidState fluid, boolean waterlogProperty, boolean waterlogged) {
    public Object getBlock() { return block; }
    public FluidState getFluidState() { return fluid; }
    public boolean hasProperty(Object property) { return waterlogProperty; }
    public boolean getValue(Object property) { return waterlogged; }
    public boolean is(Object tag) {
        return tag == net.minecraft.tags.BlockTags.SUPPORTS_SUGAR_CANE_ADJACENTLY
            && net.minecraft.world.level.block.Blocks.SUGAR_CANE_SUPPORT.contains(block);
    }
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
    public void remove(int x,int y,int z) { states.remove(x+","+y+","+z); }
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
    static final BlockState LOGGED = new BlockState(Blocks.SOLID,new FluidState(true,true),true,true);
    static final BlockState LOGGED_FALLBACK = new BlockState(Blocks.SOLID,new FluidState(false,false),true,true);
    static final BlockState DRY_LOGGABLE = new BlockState(Blocks.SOLID,new FluidState(false,false),true,false);
    static final BlockState OTHER_FLUID = new BlockState(Blocks.SOLID,new FluidState(false,true),false,false);
    static final BlockState FROSTED_ICE = new BlockState(Blocks.FROSTED_ICE,new FluidState(false,false),false,false);
    static final BlockState ICE = new BlockState(Blocks.ICE,new FluidState(false,false),false,false);
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
            check(!WaterProximityChecker.hasNoWaterNearby(world(x,y,z,FLOWING),ORIGIN),
                "flowing water inside scan: "+x+","+y+","+z);
        }
        for(int[] xyz:new int[][] {{-5,0,0},{5,1,0},{0,0,-5},{0,1,5},{0,-1,0},{0,2,0},
                {-5,1,-4},{4,0,5}}) {
            for(BlockState state:new BlockState[] {SOURCE,FLOWING,LOGGED})
                check(WaterProximityChecker.hasNoWaterNearby(world(xyz[0],xyz[1],xyz[2],state),ORIGIN),
                    "water outside scan: "+java.util.Arrays.toString(xyz));
        }
        for(int y=0;y<=1;y++) {
            check(!WaterProximityChecker.hasNoWaterNearby(world(4,y,-4,LOGGED),ORIGIN),"waterlogged accepted");
            check(!WaterProximityChecker.hasNoWaterNearby(world(4,y,-4,LOGGED_FALLBACK),ORIGIN),"waterlogged property fallback preserved");
            check(WaterProximityChecker.hasNoWaterNearby(world(0,y,0,DRY_LOGGABLE),ORIGIN),"dry waterloggable ignored");
            check(WaterProximityChecker.hasNoWaterNearby(world(0,y,0,OTHER_FLUID),ORIGIN),"other source fluid ignored");
            check(WaterProximityChecker.hasNoWaterNearby(world(0,y,0,FROSTED_ICE),ORIGIN),"frosted ice does not hydrate farmland");
            check(WaterProximityChecker.hasNoWaterNearby(world(0,y,0,ICE),ORIGIN),"ordinary ice does not hydrate farmland");
        }
        // A source stays outside hydration range. Breaking a barrier lets its
        // flowing water enter range without moving the player or target block.
        for(int y=0;y<=1;y++) {
            Level changing=world(5,y,0,SOURCE);
            int x=ORIGIN.getX()+4, wy=ORIGIN.getY()+y, z=ORIGIN.getZ();
            check(WaterProximityChecker.hasNoWaterNearby(changing,ORIGIN),"dry before water flows in");
            changing.put(x,wy,z,FLOWING);
            check(!WaterProximityChecker.hasNoWaterNearby(changing,ORIGIN),"flow update hydrates previously dry dirt");
            changing.remove(x,wy,z);
            check(WaterProximityChecker.hasNoWaterNearby(changing,ORIGIN),"flow removal immediately makes dirt dry");
            changing.put(x,wy,z,SOURCE);
            check(!WaterProximityChecker.hasNoWaterNearby(changing,ORIGIN),"source update hydrates dirt");
            changing.put(x,wy,z,FLOWING);
            check(!WaterProximityChecker.hasNoWaterNearby(changing,ORIGIN),"source becoming flowing stays hydrating");
            changing.put(x,wy,z,DRY_LOGGABLE);
            check(WaterProximityChecker.hasNoWaterNearby(changing,ORIGIN),"solid replacement removes hydration");
            changing.put(x,wy,z,LOGGED);
            check(!WaterProximityChecker.hasNoWaterNearby(changing,ORIGIN),"waterlogging update hydrates dirt");
            changing.put(x,wy,z,DRY_LOGGABLE);
            check(WaterProximityChecker.hasNoWaterNearby(changing,ORIGIN),"draining waterlogged block removes hydration");
        }
        // Match vanilla sugar-cane support tags, not farmland hydration or source-only water.
        check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(new Level(),ORIGIN),"no adjacent water");
        for(int[] xyz:new int[][] {{1,0,0},{-1,0,0},{0,0,1},{0,0,-1}}) {
            int x=xyz[0],y=xyz[1],z=xyz[2];
            check(WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,SOURCE),ORIGIN),"adjacent source accepted");
            check(WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,LOGGED),ORIGIN),"adjacent logged accepted");
            check(WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,FLOWING),ORIGIN),"adjacent flowing accepted");
            check(WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,FROSTED_ICE),ORIGIN),"adjacent frosted ice accepted");
            check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,ICE),ORIGIN),"adjacent ordinary ice ignored");
            check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,DRY_LOGGABLE),ORIGIN),"adjacent dry ignored");
            check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(x,y,z,OTHER_FLUID),ORIGIN),"adjacent other fluid ignored");
        }
        for(int[] xyz:new int[][] {{0,1,0},{0,-1,0},{1,1,0},{1,-1,0},{1,0,1},{2,0,0},{0,0,0}}) {
            for(BlockState state:new BlockState[] {SOURCE,FLOWING,LOGGED,FROSTED_ICE})
                check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(xyz[0],xyz[1],xyz[2],state),ORIGIN),
                    "non-horizontal-neighbor ignored: "+java.util.Arrays.toString(xyz));
        }
        // Data packs/mods may extend support tags without changing water hydration.
        Object customBlock=new Object();
        BlockState customSupport=new BlockState(customBlock,new FluidState(false,false),false,false);
        Level tagged=world(1,0,0,customSupport);
        check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(tagged,ORIGIN),"untagged block ignored");
        Blocks.SUGAR_CANE_SUPPORT.add(customBlock);
        check(WaterProximityChecker.isAdjacentToSourceWaterHorizontally(tagged,ORIGIN),"custom block support tag accepted");
        check(WaterProximityChecker.hasNoWaterNearby(tagged,ORIGIN),"custom block support does not hydrate farmland");
        Blocks.SUGAR_CANE_SUPPORT.remove(customBlock);
        check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(tagged,ORIGIN),"removed support tag rechecked");
        BlockState customFluid=new BlockState(Blocks.SOLID,new FluidState(false,false,true),false,false);
        check(WaterProximityChecker.isAdjacentToSourceWaterHorizontally(world(1,0,0,customFluid),ORIGIN),"custom fluid support tag accepted");
        check(WaterProximityChecker.hasNoWaterNearby(world(1,0,0,customFluid),ORIGIN),"non-water support fluid does not hydrate farmland");
        Level changingAdjacent=new Level();
        check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(changingAdjacent,ORIGIN),"adjacent initially dry");
        changingAdjacent.put(ORIGIN.getX()+1,ORIGIN.getY(),ORIGIN.getZ(),FLOWING);
        check(WaterProximityChecker.isAdjacentToSourceWaterHorizontally(changingAdjacent,ORIGIN),"new adjacent flowing water rechecked");
        changingAdjacent.remove(ORIGIN.getX()+1,ORIGIN.getY(),ORIGIN.getZ());
        check(!WaterProximityChecker.isAdjacentToSourceWaterHorizontally(changingAdjacent,ORIGIN),"adjacent water removal rechecked");
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
