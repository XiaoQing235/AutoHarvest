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
public class BlockPos {
    private int x,y,z;
    public static long visits;
    public BlockPos(int x,int y,int z) { this.x=x;this.y=y;this.z=z; }
    public int getX() { return x; }
    public int getY() { return y; }
    public int getZ() { return z; }
    public int x() { return x; }
    public int y() { return y; }
    public int z() { return z; }
    public BlockPos immutable() { return new BlockPos(x,y,z); }
    public boolean equals(Object o) { return o instanceof BlockPos p && x==p.x && y==p.y && z==p.z; }
    public int hashCode() { return (x*31+y)*31+z; }
    public String toString() { return x+","+y+","+z; }
    public static BlockPos containing(Vec3 v) {
        return new BlockPos((int)Math.floor(v.x),(int)Math.floor(v.y),(int)Math.floor(v.z));
    }
    // Lazy Manhattan-distance shells, with one borrowed mutable position. Ties
    // need not match Minecraft; distance ordering and aliasing match its contract.
    public static Iterable<BlockPos> withinManhattan(BlockPos p,int rx,int ry,int rz) {
        return () -> new Iterator<>() {
            final int ox=p.x,oy=p.y,oz=p.z;
            final BlockPos mutable=new BlockPos(0,0,0);
            int depth=0, dx=0, dy=0, nextX,nextY,nextZ;
            boolean ready,mirror;
            public boolean hasNext() {
                if(ready) return true;
                if(mirror) { mirror=false;nextZ=-nextZ;ready=true;return true; }
                while(depth<=rx+ry+rz) {
                    int maxX=Math.min(rx,depth);
                    if(dx>maxX) { depth++;dx=-Math.min(rx,depth);dy=-Math.min(ry,depth-Math.abs(dx));continue; }
                    int maxY=Math.min(ry,depth-Math.abs(dx));
                    if(dy>maxY) { dx++;dy=-Math.min(ry,depth-Math.abs(dx));continue; }
                    int z=depth-Math.abs(dx)-Math.abs(dy);
                    int y=dy++;
                    if(z>rz) continue;
                    nextX=dx;nextY=y;nextZ=z;mirror=z!=0;ready=true;return true;
                }
                return false;
            }
            public BlockPos next() {
                if(!hasNext()) throw new NoSuchElementException();
                ready=false;visits++;
                mutable.x=ox+nextX;mutable.y=oy+nextY;mutable.z=oz+nextZ;
                return mutable;
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
                    if (dx*dx+dy*dy+dz*dz<r*r) values.add(new BlockPos(x,y,z));
                }
        return values;
    }
    static Set<BlockPos> tick(Vec3 center,double radius,BoxUtil.ScanCursor cursor,
                              Set<BlockPos> eligible,int budget) {
        Set<BlockPos> acted=new HashSet<>();
        int[] callbacks={0};
        BlockPos.visits=0;
        BoxUtil.forEachBlockInRange(center,radius,cursor,p->{
            callbacks[0]++;
            check(!BoxUtil.isOutsideSphere(p,center,radius),"live selection range");
            if(!eligible.contains(p)) return false;
            check(acted.add(p.immutable()),"duplicate action in one invocation: "+p);
            cursor.rememberTarget(p);
            return acted.size()>=budget;
        });
        check(BlockPos.visits<=BoxUtil.MAX_BLOCKS_PER_SCAN,"raw scan work bounded");
        check(callbacks[0]<=BoxUtil.MAX_BLOCKS_PER_SCAN,"callback work bounded");
        check(acted.size()<=budget,"action budget");
        return acted;
    }
    public static void main(String[] args) {
        for (Vec3 center:List.of(new Vec3(0,0,0),new Vec3(-3.2,2.75,-.5),new Vec3(.5,.5,.5))) {
            for (double r:new double[]{1,1.1,3.5,4.5,6.5}) {
                Set<BlockPos> actual=new HashSet<>();
                BlockPos.visits=0;
                BoxUtil.forEachBlockInRange(center,r,new BoxUtil.ScanCursor(),p->{
                    check(actual.add(p.immutable()),"duplicate in ordinary full cycle");return false;});
                check(actual.equals(expected(center,r)),"legacy sphere mismatch r="+r);
                check(BlockPos.visits<=BoxUtil.MAX_BLOCKS_PER_SCAN,"small scan budget");
            }
        }
        Vec3 center=new Vec3(.5,.5,.5);
        BoxUtil.ScanCursor cursor=new BoxUtil.ScanCursor();
        BlockPos near=new BlockPos(0,0,0),far=new BlockPos(2,0,0);
        Set<BlockPos> pair=Set.of(near,far);
        check(tick(center,4.5,cursor,pair,1).contains(near),"nearest first");
        check(tick(center,4.5,cursor,pair,1).contains(far),"unchanged nearest must not starve next target");
        // More budget than candidates: wrapping/cache/local passes must not resend.
        for(double r:new double[]{1,4.5,6.5,10,20}) {
            cursor.reset();
            Set<BlockPos> all=new HashSet<>();
            for(int n=0;n<20;n++) {
                Set<BlockPos> acted=tick(center,r,cursor,Set.of(near),64);
                check(acted.size()==1,"sparse repeating target has no idle invocation r="+r);
                all.addAll(acted);
            }
            check(all.equals(Set.of(near)),"mutable iterator did not move remembered target");
        }
        // Targets outside the local pass are retained too, e.g. bonemeal at range 12.
        cursor.reset();
        BlockPos outer=new BlockPos(9,0,0);
        boolean discovered=false;
        for(int n=0;n<30;n++) {
            Set<BlockPos> acted=tick(center,20,cursor,Set.of(outer),1);
            if(discovered) check(acted.contains(outer),"remembered outer target stalled");
            discovered|=acted.contains(outer);
        }
        check(discovered,"outer candidate discovered");
        Set<BlockPos> retried=new HashSet<>();
        for(int n=0;n<4;n++) retried.addAll(tick(center,20,cursor,Set.of(near,outer),1));
        check(retried.equals(Set.of(near,outer)),"local repeater starves remembered outer target");
        // Nearby repeaters cannot prevent discovery of far targets.
        cursor.reset();
        BlockPos edge=new BlockPos(18,0,0);
        boolean reachedEdge=false;
        for(int n=0;n<80;n++) reachedEdge|=tick(center,20,cursor,Set.of(near,edge),1).contains(edge);
        check(reachedEdge,"background sweep starved by remembered targets");
        // New nearby work must be discovered while the background sweep is far away.
        cursor.reset();
        for(int n=0;n<5;n++) tick(center,100,cursor,Set.of(),64);
        Vec3 walking=new Vec3(2.5,.5,.5);
        BlockPos newlyNear=new BlockPos(2,0,0);
        check(tick(walking,100,cursor,Set.of(newlyNear),1).contains(newlyNear),"new local target while walking");
        check(tick(walking,100,cursor,Set.of(newlyNear,new BlockPos(3,0,0)),1)
                .contains(new BlockPos(3,0,0)),"local cursor must not starve neighbor");
        // Small-range movement must refill the next sweep without an idle tick.
        cursor.reset();
        BlockPos last=new BlockPos(2,0,0);
        tick(center,2.5,cursor,Set.of(last),1);
        Vec3 moved=new Vec3(1.5,.5,.5);
        check(tick(moved,2.5,cursor,Set.of(new BlockPos(3,0,0)),1).size()==1,"moving sweep transition idle");
        // Empty scans cover the full large sphere despite bounded repeated local work.
        cursor.reset();
        Set<BlockPos> covered=new HashSet<>();
        for(int n=0;n<5;n++) {
            BlockPos.visits=0;
            BoxUtil.forEachBlockInRange(center,10,cursor,p->{covered.add(p.immutable());return false;});
            check(BlockPos.visits<=4096,"full coverage work bound");
        }
        check(covered.equals(expected(center,10)),"large scan omitted positions");
        // World/range/teleport resets and explicit disable release cached targets.
        cursor.reset();tick(center,20,cursor,Set.of(outer),64);
        Minecraft.getInstance().level=new ClientLevel();
        check(tick(center,1,cursor,Set.of(near,outer),64).equals(Set.of(near)),"world/range reset");
        Vec3 teleported=new Vec3(1000.5,.5,.5);
        check(tick(teleported,20,cursor,Set.of(new BlockPos(1000,0,0),near),1)
                .contains(new BlockPos(1000,0,0)),"teleport restarts nearby");
        for(double invalid:new double[]{0,-1,Double.NaN,Double.POSITIVE_INFINITY}) {
            BlockPos.visits=0;
            BoxUtil.forEachBlockInRange(center,invalid,cursor,p->{throw new AssertionError("invalid radius callback");});
            check(BlockPos.visits==0,"invalid radius scanned");
        }
        // Candidate invalidation, eviction and batch size 64 remain bounded and distinct.
        cursor.reset();
        Set<BlockPos> dense=expected(center,6.5);
        for(int n=0;n<30;n++) check(tick(center,6.5,cursor,dense,64).size()==64,"dense batch lost actions");
        check(tick(center,6.5,cursor,Set.of(),64).isEmpty(),"stale candidate dispatched");
        check(BoxUtil.isOutsideSphere(new BlockPos(1,0,0),center,1),"strict boundary");
        System.out.println("PASS: "+assertions+" scan assertions (mutable Manhattan API stub, not Minecraft)");
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
