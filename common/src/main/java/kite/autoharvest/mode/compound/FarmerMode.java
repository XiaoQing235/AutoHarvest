package kite.autoharvest.mode.compound;

import kite.autoharvest.config.AutoHarvestConfig;
import kite.autoharvest.mode.AutoMode;
import kite.autoharvest.util.BoxUtil;
import kite.autoharvest.util.InteractionHelper;
import kite.autoharvest.util.InteractionRange;
import kite.autoharvest.util.ItemRefillHelper;
import kite.autoharvest.util.ItemSlotHelper;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ContainerInput;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.Holder;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.Registries;
import net.minecraft.network.chat.Component;
import net.minecraft.tags.ItemTags;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.item.enchantment.Enchantment;
import net.minecraft.world.item.enchantment.Enchantments;
import net.minecraft.world.item.enchantment.ItemEnchantments;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.CropBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.BlockStateProperties;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;

public class FarmerMode implements AutoMode {
    private static final Set<Block> HARVEST_CROPS = Set.of(
            Blocks.WHEAT,
            Blocks.CARROTS,
            Blocks.POTATOES,
            Blocks.BEETROOTS,
            Blocks.NETHER_WART,
            Blocks.SUGAR_CANE,
            Blocks.SWEET_BERRY_BUSH
    );

    private static final Map<Block, Item> CROP_TO_SEED = Map.of(
            Blocks.WHEAT, Items.WHEAT_SEEDS,
            Blocks.CARROTS, Items.CARROT,
            Blocks.POTATOES, Items.POTATO,
            Blocks.BEETROOTS, Items.BEETROOT_SEEDS,
            Blocks.NETHER_WART, Items.NETHER_WART
    );

    private static final Set<Item> REFILLABLE_SEEDS = Set.copyOf(CROP_TO_SEED.values());

    private static final int MAX_PENDING_PLANTS = 512;
    private static final long BREAK_OBSERVATION_TIMEOUT_TICKS = 10;
    private static final long PLANT_EXPIRY_TICKS = 1200;
    private static final long PLANT_RETRY_TICKS = 10;
    private static final long PLANT_PREDICTION_GRACE_TICKS = 40;

    private boolean pendingBreak;
    private BlockPos targetPos;
    private Item targetSeed;
    private Block targetBlock;
    private boolean targetInteract;
    private ClientLevel activeWorld;
    private Holder<Enchantment> fortuneHolder;
    private final BoxUtil.ScanCursor scanCursor = new BoxUtil.ScanCursor();
    private final Map<BlockPos, PendingPlant> pendingPlant = new HashMap<>();

    private record PendingPlant(Item seed, BlockState harvestedState, long expiresAt,
                                long retryAt, boolean observedAir, long observedPlantAt) {}

    @Override
    public void tick() {
        Minecraft client = Minecraft.getInstance();
        ClientLevel world = client.level;
        LocalPlayer player = client.player;
        if (world == null || player == null) return;
        if (world != activeWorld) {
            onDisable();
            activeWorld = world;
        }

        if (AutoHarvestConfig.enableRefill() && !player.isCreative() && !player.isSpectator()) {
            ItemStack mainStack = player.getMainHandItem();
            ItemStack offStack = player.getOffhandItem();
            if (!mainStack.isEmpty() && mainStack.getCount() < 64 && REFILLABLE_SEEDS.contains(mainStack.getItem())) {
                ItemRefillHelper.refillMainHand();
            }
            if (!offStack.isEmpty() && offStack.getCount() < 64 && REFILLABLE_SEEDS.contains(offStack.getItem())) {
                ItemRefillHelper.refillOffHand();
            }
        }

        // One budget for all world operations: planting, breaking and berry picking.
        // Inventory changes are not world operations. A Fortune switch always waits
        // until the next scheduled mode tick; increasing this budget cannot skip it.
        int budget = AutoHarvestConfig.maxActionsPerTick();
        Set<BlockPos> attempted = new HashSet<>();
        prunePendingPlants(world);
        if (pendingBreak) {
            if (isTargetValid(world, player)) {
                int fortuneSlot = findFortuneToolSlotIfEnabled(player);
                if (switchFortuneTool(player, fortuneSlot)) return;
                attempted.add(targetPos);
                if (executeHarvest(world, player)) budget--;
            }
            clearTarget();
        } else {
            budget -= processPendingPlant(world, player, budget, attempted);
        }
        if (budget > 0) scanAndHarvest(world, player, budget, attempted);
    }

    private void prunePendingPlants(ClientLevel world) {
        long now = world.getGameTime();
        pendingPlant.entrySet().removeIf(entry -> {
            PendingPlant pending = entry.getValue();
            BlockState current = world.getBlockState(entry.getKey());
            if (current.isAir()) {
                if (!pending.observedAir()) {
                    // Observe air before the short break deadline: scheduled mode
                    // ticks may be farther apart. Missing seeds retain this job.
                    entry.setValue(new PendingPlant(pending.seed(), pending.harvestedState(),
                            now + PLANT_EXPIRY_TICKS, pending.retryAt(), true, -1));
                    return false;
                }
                if (now >= pending.expiresAt()) return true;
                if (pending.observedPlantAt() >= 0) {
                    // Predicted planting rolled back. Keep the existing placement
                    // backoff and lifetime, but restart the observation grace.
                    entry.setValue(new PendingPlant(pending.seed(), pending.harvestedState(),
                            pending.expiresAt(), pending.retryAt(), true, -1));
                }
                return false;
            }
            if (now >= pending.expiresAt()) return true;
            if (!pending.observedAir()) {
                return current != pending.harvestedState();
            }
            // A mature original crop may be a reverted break or a regrown crop;
            // release it for harvesting. An unrelated block invalidates the job.
            if (current == pending.harvestedState()
                    || !current.is(pending.harvestedState().getBlock())) return true;
            // Client state is not server confirmation. Watch a matching planted
            // crop for a bounded grace period to tolerate common prediction rollbacks.
            if (pending.observedPlantAt() < 0) {
                entry.setValue(new PendingPlant(pending.seed(), pending.harvestedState(),
                        pending.expiresAt(), pending.retryAt(), true, now));
                return false;
            }
            return now - pending.observedPlantAt() >= PLANT_PREDICTION_GRACE_TICKS;
        });
    }

    private int processPendingPlant(ClientLevel world, LocalPlayer player, int budget, Set<BlockPos> attempted) {
        int actions = 0;
        long now = world.getGameTime();
        Iterator<Map.Entry<BlockPos, PendingPlant>> iterator = pendingPlant.entrySet().iterator();
        while (iterator.hasNext() && actions < budget) {
            Map.Entry<BlockPos, PendingPlant> entry = iterator.next();
            BlockPos pos = entry.getKey();
            PendingPlant pending = entry.getValue();
            if (!world.getBlockState(pos).isAir()) continue;
            if (!isPlantableBelow(player, pos, pending.seed())) {
                iterator.remove();
                continue;
            }
            if (now < pending.retryAt() || !isWithinSelectionRange(player, pos)
                    || !InteractionRange.canReachBlock(player, pos.below())) continue;
            if (doPlant(player, pos, pending.seed())) {
                attempted.add(pos);
                actions++;
                entry.setValue(new PendingPlant(pending.seed(), pending.harvestedState(),
                        pending.expiresAt(), now + PLANT_RETRY_TICKS, pending.observedAir(),
                        pending.observedPlantAt()));
            }
        }
        return actions;
    }

    private boolean isPlantableBelow(LocalPlayer player, BlockPos pos, Item seed) {
        Block below = player.level().getBlockState(pos.below()).getBlock();
        return seed == Items.NETHER_WART ? below == Blocks.SOUL_SAND : below == Blocks.FARMLAND;
    }

    private void scanAndHarvest(ClientLevel world, LocalPlayer player, int budget, Set<BlockPos> attempted) {
        int[] remaining = {budget};
        // Resolve Fortune once, lazily, after planting has finished changing slots.
        int[] fortuneSlot = {-2};
        BoxUtil.forEachBlockInRange(InteractionRange.scanCenter(player),
                InteractionRange.blockScanRadius(player), scanCursor, pos -> {
            BlockState state = world.getBlockState(pos);
            Block block = state.getBlock();
            if (!HARVEST_CROPS.contains(block)) return false;
            if (CROP_TO_SEED.containsKey(block) && pendingPlant.size() >= MAX_PENDING_PLANTS) return false;
            BlockPos harvestPos = pos;
            if (block == Blocks.SUGAR_CANE) {
                if (world.getBlockState(pos.below()).is(Blocks.SUGAR_CANE)
                        || !world.getBlockState(pos.above()).is(Blocks.SUGAR_CANE)) return false;
                harvestPos = pos.above();
            } else if (isNotFullyGrown(state, block)) {
                return false;
            }
            if (attempted.contains(harvestPos) || pendingPlant.containsKey(harvestPos)
                    || !InteractionRange.canReachBlock(player, harvestPos)) return false;

            // Scan iterators reuse mutable positions; queued targets must own a copy.
            targetPos = harvestPos.immutable();
            targetBlock = block;
            targetSeed = CROP_TO_SEED.get(block);
            targetInteract = block == Blocks.SWEET_BERRY_BUSH;
            if (fortuneSlot[0] == -2) fortuneSlot[0] = findFortuneToolSlotIfEnabled(player);
            if (switchFortuneTool(player, fortuneSlot[0])) {
                pendingBreak = true;
                return true;
            }
            attempted.add(targetPos);
            if (executeHarvest(world, player)) {
                remaining[0]--;
                scanCursor.rememberTarget(pos);
            }
            clearTarget();
            return remaining[0] <= 0;
        });
    }

    private boolean isTargetValid(ClientLevel world, LocalPlayer player) {
        if (targetPos == null || !InteractionRange.canReachBlock(player, targetPos)) return false;
        BlockPos scanPos = targetBlock == Blocks.SUGAR_CANE ? targetPos.below() : targetPos;
        if (!isWithinSelectionRange(player, scanPos)) return false;
        BlockState state = world.getBlockState(targetPos);
        if (!state.is(targetBlock)) return false;
        if (targetBlock == Blocks.SUGAR_CANE) return world.getBlockState(targetPos.below()).is(Blocks.SUGAR_CANE);
        return !isNotFullyGrown(state, targetBlock);
    }

    private boolean isWithinSelectionRange(LocalPlayer player, BlockPos pos) {
        return AutoHarvestConfig.usePlayerRange()
                || !BoxUtil.isOutsideSphere(pos, player.position(), InteractionRange.blockRadius(player));
    }

    private boolean executeHarvest(ClientLevel world, LocalPlayer player) {
        // Also guard deferred Fortune targets: never harvest a seed crop if its
        // replant job cannot be retained. Berry/cane operations need no entry.
        if (targetSeed != null && pendingPlant.size() >= MAX_PENDING_PLANTS) return false;
        BlockState state = world.getBlockState(targetPos);
        boolean dispatched = targetInteract
                ? InteractionHelper.interactBlock(player, targetPos, InteractionHand.MAIN_HAND, Direction.UP)
                : InteractionHelper.breakBlock(targetPos, Direction.UP);
        if (dispatched && targetSeed != null) {
            pendingPlant.put(targetPos, new PendingPlant(targetSeed, state,
                    world.getGameTime() + BREAK_OBSERVATION_TIMEOUT_TICKS, 0, false, -1));
        }
        return dispatched;
    }

    private void clearTarget() {
        pendingBreak = false;
        targetPos = null;
        targetSeed = null;
        targetBlock = null;
        targetInteract = false;
    }

    private int findFortuneToolSlotIfEnabled(LocalPlayer player) {
        return AutoHarvestConfig.autoSwitchFortuneTool() ? findFortuneToolSlot(player) : -1;
    }

    private boolean switchFortuneTool(LocalPlayer player, int slot) {
        if (slot < 0 || player.getInventory().getSelectedSlot() == slot) return false;
        player.getInventory().setSelectedSlot(slot);
        return true;
    }

    private int findSeedSlot(LocalPlayer player, Item seed) {
        if (player.getMainHandItem().getItem() == seed) {
            return player.getInventory().getSelectedSlot();
        }
        if (player.getOffhandItem().getItem() == seed) {
            return -2;
        }
        int hotbarSlot = ItemSlotHelper.findNearestSlot(player, seed);
        if (hotbarSlot != -1) return hotbarSlot;

        for (int i = 9; i < 36; i++) {
            if (player.getInventory().getItem(i).getItem() == seed) {
                return i;
            }
        }
        return -1;
    }

    private boolean doPlant(LocalPlayer player, BlockPos pos, Item seed) {
        int slot = findSeedSlot(player, seed);
        if (slot == -1) return false;

        boolean offhand = AutoHarvestConfig.farmerOffhandPlant();
        ensureSeedAvailable(player, slot, offhand);
        return InteractionHelper.interactBlock(player, pos.below(), offhand ? InteractionHand.OFF_HAND : InteractionHand.MAIN_HAND, Direction.UP);
    }

    private void ensureSeedAvailable(LocalPlayer player, int slot, boolean offhand) {
        if (offhand) {
            if (slot == -2) return;
            if (slot < 9) {
                swapContainerSlots(player.containerMenu, slot + 36, 45);
            } else {
                swapContainerSlots(player.containerMenu, slot, 45);
            }
            return;
        }

        if (slot == -2) {
            swapContainerSlots(player.containerMenu, player.getInventory().getSelectedSlot() + 36, 45);
            return;
        }

        if (slot < 9) {
            player.getInventory().setSelectedSlot(slot);
            return;
        }

        int hotbarSlot = findHotbarInsertSlot(player);
        swapContainerSlots(player.containerMenu, slot, hotbarSlot + 36);
        player.getInventory().setSelectedSlot(hotbarSlot);
    }

    private void swapContainerSlots(AbstractContainerMenu handler, int sourceSlot, int targetSlot) {
        clickSlot(handler, sourceSlot);
        clickSlot(handler, targetSlot);
        if (!handler.getCarried().isEmpty()) {
            clickSlot(handler, sourceSlot);
        }
    }

    private void clickSlot(AbstractContainerMenu handler, int slotIndex) {
        var client = Minecraft.getInstance();
        if (client.gameMode == null) return;
        if (client.player != null) {
            client.gameMode.handleContainerInput(
                    handler.containerId,
                    slotIndex,
                    0,
                    ContainerInput.PICKUP,
                    client.player
            );
        }
    }

    private int findHotbarInsertSlot(LocalPlayer player) {
        for (int i = 0; i < 9; i++) {
            if (player.getInventory().getItem(i).isEmpty()) return i;
        }
        Holder<Enchantment> fortuneHolder = fortuneHolder(player);
        for (int i = 0; i < 9; i++) {
            if (!isFortuneTool(player.getInventory().getItem(i), fortuneHolder)) return i;
        }
        return 0;
    }

    private int findFortuneToolSlot(LocalPlayer player) {
        Holder<Enchantment> fortuneHolder = fortuneHolder(player);

        for (int i = 0; i < 9; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;

            if (isFortuneTool(stack, fortuneHolder)) return i;
        }
        return -1;
    }

    private boolean isHarvestTool(ItemStack stack) {
        return stack.is(ItemTags.AXES) ||
                stack.is(ItemTags.SHOVELS) ||
                stack.is(ItemTags.HOES) ||
                stack.is(ItemTags.PICKAXES);
    }

    private Holder<Enchantment> fortuneHolder(LocalPlayer player) {
        if (fortuneHolder == null) {
            fortuneHolder = player.level().registryAccess()
                    .lookupOrThrow(Registries.ENCHANTMENT).getOrThrow(Enchantments.FORTUNE);
        }
        return fortuneHolder;
    }

    private boolean isFortuneTool(ItemStack stack, Holder<Enchantment> fortuneHolder) {
        if (stack.isEmpty() || !isHarvestTool(stack)) return false;
        ItemEnchantments enchantments = stack.getOrDefault(DataComponents.ENCHANTMENTS, ItemEnchantments.EMPTY);
        return enchantments.getLevel(fortuneHolder) >= 1;
    }

    private boolean isNotFullyGrown(BlockState state, Block block) {
        if (block == Blocks.NETHER_WART) {
            return state.getValue(BlockStateProperties.AGE_3) < 3;
        } else if (block == Blocks.SWEET_BERRY_BUSH) {
            return state.getValue(BlockStateProperties.AGE_3) < 2;
        } else if (block instanceof CropBlock) {
            if (block == Blocks.BEETROOTS) {
                return state.getValue(BlockStateProperties.AGE_3) < 3;
            } else {
                return state.getValue(BlockStateProperties.AGE_7) < 7;
            }
        }
        return false;
    }

    @Override
    public String getName() {
        return Component.translatable("autoharvest.mode.farmer").getString();
    }

    @Override
    public void onDisable() {
        clearTarget();
        pendingPlant.clear();
        scanCursor.reset();
        activeWorld = null;
        fortuneHolder = null;
    }
}
