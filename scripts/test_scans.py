#!/usr/bin/env python3
"""Test the real BoxUtil against minimal API stubs, without Gradle or Minecraft.

Requires Python 3 and a JDK. This is a helper regression test, NOT a mod build,
Minecraft API compatibility check, or Fabric/NeoForge integration test.
"""
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = {
    'net/minecraft/world/phys/Vec3.java': """package net.minecraft.world.phys;
public class Vec3 {
    public final double x,y,z;
    public Vec3(double x,double y,double z) { this.x=x;this.y=y;this.z=z; }
}""",
    'net/minecraft/world/phys/AABB.java': '''package net.minecraft.world.phys;
public record AABB(double minX,double minY,double minZ,double maxX,double maxY,double maxZ) {}''',
    'net/minecraft/client/multiplayer/ClientLevel.java': '''package net.minecraft.client.multiplayer;
public class ClientLevel {}''',
    'net/minecraft/client/player/LocalPlayer.java': '''package net.minecraft.client.player;
import net.minecraft.world.phys.Vec3;
public class LocalPlayer { public Vec3 position() { return new Vec3(0,0,0); } }''',
    'net/minecraft/client/Minecraft.java': '''package net.minecraft.client;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
public class Minecraft {
    private static final Minecraft INSTANCE = new Minecraft();
    public ClientLevel level = new ClientLevel();
    public LocalPlayer player = new LocalPlayer();
    public static Minecraft getInstance() { return INSTANCE; }
}''',
    'net/minecraft/core/BlockPos.java': '''package net.minecraft.core;
import java.util.Iterator;
import java.util.NoSuchElementException;
import net.minecraft.world.phys.Vec3;
public record BlockPos(int x,int y,int z) {
    public static long visits;
    public int getX() { return x; }
    public int getY() { return y; }
    public int getZ() { return z; }
    public static BlockPos containing(Vec3 v) {
        return new BlockPos((int)Math.floor(v.x),(int)Math.floor(v.y),(int)Math.floor(v.z));
    }
    // Lazy cube test double. Production uses Minecraft's Manhattan traversal order.
    public static Iterable<BlockPos> withinManhattan(BlockPos p,int rx,int ry,int rz) {
        return () -> new Iterator<>() {
            long index;
            final long sx = 2L*rx+1, sy = 2L*ry+1, sz = 2L*rz+1;
            public boolean hasNext() { return index < sx*sy*sz; }
            public BlockPos next() {
                if (!hasNext()) throw new NoSuchElementException();
                long i = index++;
                visits++;
                return new BlockPos(p.x-rx+(int)(i%sx),p.y-ry+(int)(i/sx%sy),p.z-rz+(int)(i/(sx*sy)));
            }
        };
    }
}''',
    'ScanTest.java': '''import kite.autoharvest.util.BoxUtil;
import net.minecraft.core.BlockPos;
import net.minecraft.world.phys.Vec3;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import java.util.*;
public class ScanTest {
    static int assertions;
    static void check(boolean value,String message) {
        assertions++;
        if (!value) throw new AssertionError(message);
    }
    static Set<BlockPos> expected(Vec3 center,double r) {
        Set<BlockPos> values = new HashSet<>();
        BlockPos origin = BlockPos.containing(center);
        int ri = (int)Math.ceil(r);
        for (int x=origin.x()-ri;x<=origin.x()+ri;x++)
            for (int y=origin.y()-ri;y<=origin.y()+ri;y++)
                for (int z=origin.z()-ri;z<=origin.z()+ri;z++) {
                    double dx=x+.5-center.x,dy=y+.5-center.y,dz=z+.5-center.z;
                    // Original AABB contains + strict center distance comparison.
                    boolean box=x+.5>=center.x-r && x+.5<center.x+r
                            && y+.5>=center.y-r && y+.5<center.y+r
                            && z+.5>=center.z-r && z+.5<center.z+r;
                    if (box && dx*dx+dy*dy+dz*dz<r*r) values.add(new BlockPos(x,y,z));
                }
        return values;
    }
    public static void main(String[] args) {
        for (Vec3 center:List.of(new Vec3(0,0,0),new Vec3(-3.2,2.75,-.5),new Vec3(.5,.5,.5))) {
            for (double r: new double[]{1,1.1,3.5,4.5,6.5}) {
                Set<BlockPos> actual = new HashSet<>();
                BlockPos.visits = 0;
                BoxUtil.forEachBlockInRange(center,r,new BoxUtil.ScanCursor(),p->{actual.add(p);return false;});
                check(actual.equals(expected(center,r)),"legacy sphere mismatch r="+r);
                check(BlockPos.visits<=BoxUtil.MAX_BLOCKS_PER_SCAN,"small scan budget");
            }
        }
        Vec3 center = new Vec3(.5,.5,.5);
        double r=10;
        Set<BlockPos> expected=expected(center,r), actual=new HashSet<>();
        BoxUtil.ScanCursor cursor=new BoxUtil.ScanCursor();
        long cube=21L*21*21, total=0;
        while(total<cube) {
            BlockPos.visits=0;
            BoxUtil.forEachBlockInRange(center,r,cursor,p->{check(actual.add(p),"duplicate during resumable pass");return false;});
            check(BlockPos.visits<=4096,"large scan budget");
            total+=BlockPos.visits;
        }
        check(total==cube && actual.equals(expected),"large scan omitted positions");
        // Stopping early resumes AFTER the accepted target for large scans.
        cursor.reset();actual.clear();
        for(int n=0;n<5;n++)
            BoxUtil.forEachBlockInRange(center,r,cursor,p->{check(actual.add(p),"early stop duplicate");return true;});
        check(actual.size()==5,"early stop progress");
        // Ordinary movement must not restart a large sweep and starve distant targets.
        cursor.reset();
        Set<BlockPos> movingVisited=new HashSet<>();
        total=0;
        for(int n=0;total<cube;n++) {
            BlockPos.visits=0;
            Vec3 walking=new Vec3(.5+n%3,.5,.5);
            BoxUtil.forEachBlockInRange(walking,r,cursor,p->{check(movingVisited.add(p),"walking restarted sweep");return false;});
            total+=BlockPos.visits;
        }
        check(total==cube,"movement changed sweep extent");
        // Teleports and world changes reset a partially consumed scan.
        List<BlockPos> first=new ArrayList<>();
        cursor.reset();
        BoxUtil.forEachBlockInRange(center,r,cursor,p->{first.add(p);return true;});
        Minecraft.getInstance().level=new ClientLevel();
        BoxUtil.forEachBlockInRange(center,r,cursor,p->{check(first.get(0).equals(p),"world reset");return true;});
        Vec3 moved=new Vec3(50.5,.5,.5);
        BoxUtil.forEachBlockInRange(moved,r,cursor,p->{check(p.x()>39,"movement reset");return true;});
        for(double invalid:new double[]{0,-1,Double.NaN,Double.POSITIVE_INFINITY}) {
            BlockPos.visits=0;
            BoxUtil.forEachBlockInRange(center,invalid,cursor,p->{throw new AssertionError("invalid radius callback");});
            check(BlockPos.visits==0,"invalid radius scanned");
        }
        // Exact radius boundary remains excluded, including half-block positions.
        check(BoxUtil.isOutsideSphere(new BlockPos(1,0,0),center,1),"strict boundary");
        System.out.println("PASS: "+assertions+" scan assertions (API stubs, not a Minecraft build)");
    }
}'''
}
with tempfile.TemporaryDirectory(prefix='autoharvest-scan-test-') as temp:
    work = pathlib.Path(temp)
    for name, content in SOURCES.items():
        file = work / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    production = ROOT / 'common/src/main/java/kite/autoharvest/util/BoxUtil.java'
    compiler = ['javac'] if shutil.which('javac') else ['java', 'com.sun.tools.javac.Main']
    subprocess.run([*compiler, '-source', '21', '-target', '21', '-d', str(work / 'classes'), *map(str, work.rglob('*.java')), str(production)], check=True)
    subprocess.run(['java', '-cp', str(work / 'classes'), 'ScanTest'], check=True)
