package kite.autoharvest.mode;

import kite.autoharvest.config.AutoHarvestConfig;
import kite.autoharvest.mode.animal.Animals;
import kite.autoharvest.util.*;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.network.chat.Component;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.entity.Entity;
import net.minecraft.world.entity.animal.Animal;
import net.minecraft.world.entity.animal.allay.Allay;
import net.minecraft.world.entity.animal.sheep.Sheep;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.lang.reflect.Method;
import java.util.*;

public class FeedMode implements AutoMode {

    private static final Method CAN_DUPLICATE_METHOD = initCanDuplicateMethod();

    private static Method initCanDuplicateMethod() {
        try {
            Method method = Allay.class.getDeclaredMethod("canDuplicate");
            method.setAccessible(true);
            return method;
        } catch (NoSuchMethodException e) {
            return null;
        }
    }

    private static boolean canAllayDuplicate(Allay allay) {
        if (CAN_DUPLICATE_METHOD == null) return false;
        try {
            return (boolean) CAN_DUPLICATE_METHOD.invoke(allay);
        } catch (ReflectiveOperationException e) {
            return false;
        }
    }

    private static final Map<UUID, Long> INTERACT_COOLDOWN = new HashMap<>();

    private static long COOLDOWN_MS() {
        return AutoHarvestConfig.coolDown();
    }

    private static long lastCleanupTime = 0;
    private static final long CLEANUP_INTERVAL_MS = 5_000L;

    private boolean isOnCooldown(Entity entity, long now, long cooldown) {
        Long lastInteract = INTERACT_COOLDOWN.get(entity.getUUID());
        return lastInteract != null && now - lastInteract < cooldown;
    }

    private void cleanupCooldownCache(long now, long cooldown) {
        if (now - lastCleanupTime < CLEANUP_INTERVAL_MS) return;
        INTERACT_COOLDOWN.entrySet().removeIf(entry -> now - entry.getValue() >= cooldown);
        lastCleanupTime = now;
    }

    // Initialize with Animals on first use, not during early mode registration.
    private static final class BreedFoods {
        private static final Set<Item> ALL = collect();

        private static Set<Item> collect() {
            Set<Item> foods = new HashSet<>();
            for (Set<Item> items : Animals.BREEDABLE_WHITELIST.values()) foods.addAll(items);
            return Set.copyOf(foods);
        }
    }

    private boolean canBreed(Entity entity) {
        if (entity instanceof Animal animal) {
            return !animal.isBaby();
        }
        return entity instanceof Allay allay && allay.isDancing() && canAllayDuplicate(allay);
    }

    @Override
    public void tick() {
        var breedableWhitelist = Animals.BREEDABLE_WHITELIST;
        long now = System.currentTimeMillis();
        long cooldown = COOLDOWN_MS();
        cleanupCooldownCache(now, cooldown);

        ClientLevel world = BoxUtil.getWorld();
        LocalPlayer player = BoxUtil.getPlayer();
        if (world == null || player == null) return;

        int limit = AutoHarvestConfig.maxActionsPerTick();
        int actions = 0;
        Vec3 center = InteractionRange.scanCenter(player);
        double radius = InteractionRange.entityRadius(player);
        AABB searchBox = BoxUtil.createSearchBox(center, radius);
        ItemStack mainHand = player.getMainHandItem();
        ItemStack offHand = player.getOffhandItem();
        boolean holdingShears = mainHand.is(Items.SHEARS) || offHand.is(Items.SHEARS);

        if (holdingShears) {
            List<Entity> sheepList = world.getEntities(player, searchBox, entity ->
                    entity instanceof Sheep sheep && sheep.readyForShearing()
                            && InteractionRange.canReachEntity(player, entity));
            sheepList.sort(Comparator.comparingDouble(e -> e.distanceToSqr(player)));
            for (Entity sheep : sheepList) {
                InteractionHand hand;
                if (player.getMainHandItem().is(Items.SHEARS)) hand = InteractionHand.MAIN_HAND;
                else if (player.getOffhandItem().is(Items.SHEARS)) hand = InteractionHand.OFF_HAND;
                else break;
                if (InteractionHelper.interactEntity(player, sheep, hand)) {
                    if (++actions >= limit) break;
                }
            }
            return;
        }

        boolean enableRefill = AutoHarvestConfig.enableRefill();
        boolean isCreativeOrSpectator = player.isCreative() || player.isSpectator();

        if (!isCreativeOrSpectator && enableRefill) {
            ItemStack main = player.getMainHandItem();
            ItemStack off = player.getOffhandItem();

            if (!main.isEmpty() && isBreedItem(main.getItem()) && main.getCount() < 64) {
                ItemRefillHelper.refillMainHand();
            }
            if (!off.isEmpty() && isBreedItem(off.getItem()) && off.getCount() < 64) {
                ItemRefillHelper.refillOffHand();
            }
        }

        List<Entity> entities = world.getEntities(player, searchBox, entity -> {
            Set<Item> foods = breedableWhitelist.get(entity.getClass());
            return foods != null && canBreed(entity) && !isOnCooldown(entity, now, cooldown)
                    && InteractionRange.canReachEntity(player, entity);
        });
        entities.sort(Comparator.comparingDouble(e -> e.distanceToSqr(player)));

        for (Entity target : entities) {
            Set<Item> validFoods = breedableWhitelist.get(target.getClass());
            if (validFoods == null || validFoods.isEmpty() || !canBreed(target)) continue;
            if (tryFeedEntity(player, target, validFoods)) {
                INTERACT_COOLDOWN.put(target.getUUID(), now);
                if (++actions >= limit) break;
            }
        }
    }

    private boolean isBreedItem(Item item) {
        return BreedFoods.ALL.contains(item);
    }

    private boolean tryFeedEntity(LocalPlayer player, Entity target, Set<Item> validFoods) {
        ItemStack main = player.getMainHandItem();
        ItemStack off = player.getOffhandItem();

        if (!main.isEmpty() && validFoods.contains(main.getItem())) {
            return InteractionHelper.interactEntity(player, target, InteractionHand.MAIN_HAND);
        }
        if (!off.isEmpty() && validFoods.contains(off.getItem())) {
            return InteractionHelper.interactEntity(player, target, InteractionHand.OFF_HAND);
        }

        Item bestFood = findBestFood(player, validFoods);
        if (bestFood == null) {
            return false;
        }

        int bestSlot = ItemSlotHelper.findNearestSlot(player, bestFood);
        if (bestSlot != -1 && AutoHarvestConfig.autoSwitchHotbar()) {
            player.getInventory().setSelectedSlot(bestSlot);
            return InteractionHelper.interactEntity(player, target, InteractionHand.MAIN_HAND);
        }


        return false;
    }

    private Item findBestFood(LocalPlayer player, Set<Item> validFoods) {
        if (validFoods.contains(player.getMainHandItem().getItem())) {
            return player.getMainHandItem().getItem();
        }
        if (validFoods.contains(player.getOffhandItem().getItem())) {
            return player.getOffhandItem().getItem();
        }

        return ItemSlotHelper.findNearestItem(player, validFoods);
    }


    @Override
    public String getName() {
        return Component.translatable("autoharvest.mode.feed").getString();
    }

    @Override
    public void onDisable() {
        //nothing
    }
}