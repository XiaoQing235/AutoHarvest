package kite.autoharvest.mode;

import kite.autoharvest.config.AutoHarvestConfig;
import kite.autoharvest.util.BoxUtil;
import kite.autoharvest.util.InteractionHelper;
import kite.autoharvest.util.InteractionRange;
import net.minecraft.client.Minecraft;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.Holder;
import net.minecraft.core.component.DataComponents;
import net.minecraft.core.registries.Registries;
import net.minecraft.network.chat.Component;
import net.minecraft.tags.ItemTags;
import net.minecraft.world.InteractionHand;
import net.minecraft.world.inventory.AbstractContainerMenu;
import net.minecraft.world.inventory.ContainerInput;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.enchantment.Enchantment;
import net.minecraft.world.item.enchantment.Enchantments;
import net.minecraft.world.item.enchantment.ItemEnchantments;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.CropBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.BlockStateProperties;
import net.minecraft.world.phys.Vec3;

import java.util.HashSet;
import java.util.Set;

public class HarvestMode implements AutoMode {

    private static final Set<Block> HARVEST_CROPS = Set.of(
            Blocks.WHEAT,
            Blocks.CARROTS,
            Blocks.POTATOES,
            Blocks.BEETROOTS,
            Blocks.NETHER_WART,
            Blocks.SUGAR_CANE,
            Blocks.SWEET_BERRY_BUSH,
            Blocks.BAMBOO
    );

    private final BoxUtil.ScanCursor scanCursor = new BoxUtil.ScanCursor();
    private BlockPos pendingPos;
    private Block pendingBlock;
    private ClientLevel pendingWorld;
    private boolean useInteract;

    @Override
    public void tick() {
        ClientLevel world = BoxUtil.getWorld();
        LocalPlayer player = BoxUtil.getPlayer();
        if (world == null || player == null) {
            resetPending();
            scanCursor.reset();
            return;
        }

        int limit = AutoHarvestConfig.maxActionsPerTick();
        int[] actions = {0};
        // Resolve the enchantment and inspect hotbar stacks at most once unless a sword swap changes them.
        int[] fortuneSlot = {-2};
        Set<BlockPos> attempted = new HashSet<>();
        if (pendingPos != null) {
            BlockPos pos = pendingPos;
            boolean interact = useInteract;
            boolean valid = pendingWorld == world && isPendingValid(world, pos)
                    && InteractionRange.canReachBlock(player, pos);
            resetPending();
            if (valid) {
                if (tryHarvest(world, player, pos, interact, fortuneSlot, actions, attempted)) return;
                if (actions[0] >= limit) return;
            }
        }

        Vec3 center = InteractionRange.scanCenter(player);
        double radius = InteractionRange.blockScanRadius(player);
        BoxUtil.forEachBlockInRange(center, radius, scanCursor, pos -> {
            BlockState state = world.getBlockState(pos);
            Block block = state.getBlock();
            if (!HARVEST_CROPS.contains(block)) return false;

            BlockPos target = pos;
            if (block == Blocks.SUGAR_CANE || block == Blocks.BAMBOO) {
                if (world.getBlockState(pos.below()).is(block)
                        || !world.getBlockState(pos.above()).is(block)) return false;
                target = pos.above();
            } else if (isNotFullyGrown(state, block)) {
                return false;
            }
            if (attempted.contains(target) || !InteractionRange.canReachBlock(player, target)) return false;

            if (block == Blocks.BAMBOO) {
                if (!hasSword(player)) {
                    player.sendOverlayMessage(Component.translatable("autoharvest.mode.bamboo.needSword"));
                    return true;
                }
                ensureSword(player);
                fortuneSlot[0] = -2;
                attempted.add(target.immutable());
                if (InteractionHelper.breakBlock(target, Direction.UP)) {
                    actions[0]++;
                    scanCursor.rememberTarget(pos);
                }
            } else {
                int before = actions[0];
                if (tryHarvest(world, player, target, block == Blocks.SWEET_BERRY_BUSH,
                        fortuneSlot, actions, attempted)) return true;
                if (actions[0] > before) scanCursor.rememberTarget(pos);
            }
            return actions[0] >= limit;
        });
    }

    // A hotbar switch must settle until the next scheduled mode tick before harvesting.
    private boolean tryHarvest(ClientLevel world, LocalPlayer player, BlockPos pos, boolean interact,
                               int[] fortuneSlot, int[] actions, Set<BlockPos> attempted) {
        if (AutoHarvestConfig.autoSwitchFortuneTool()) {
            if (fortuneSlot[0] == -2) fortuneSlot[0] = findFortuneToolSlot(player);
            if (fortuneSlot[0] != -1 && player.getInventory().getSelectedSlot() != fortuneSlot[0]) {
                player.getInventory().setSelectedSlot(fortuneSlot[0]);
                pendingPos = pos.immutable();
                pendingBlock = world.getBlockState(pos).getBlock();
                pendingWorld = world;
                useInteract = interact;
                return true;
            }
        }
        attempted.add(pos.immutable());
        if (executeHarvest(player, pos, interact)) actions[0]++;
        return false;
    }

    private boolean executeHarvest(LocalPlayer player, BlockPos pos, boolean interact) {
        return interact
                ? InteractionHelper.interactBlock(player, pos, InteractionHand.MAIN_HAND, Direction.UP)
                : InteractionHelper.breakBlock(pos, Direction.UP);
    }

    private boolean isPendingValid(ClientLevel world, BlockPos pos) {
        if (!AutoHarvestConfig.usePlayerRange()) {
            BlockPos scanPos = pendingBlock == Blocks.SUGAR_CANE ? pos.below() : pos;
            Vec3 center = BoxUtil.getPlayerPos();
            if (center == null || BoxUtil.isOutsideSphere(scanPos, center, AutoHarvestConfig.radius())) return false;
        }
        BlockState state = world.getBlockState(pos);
        if (!state.is(pendingBlock)) return false;
        if (pendingBlock == Blocks.SUGAR_CANE) {
            return world.getBlockState(pos.below()).is(Blocks.SUGAR_CANE)
                    && !world.getBlockState(pos.below(2)).is(Blocks.SUGAR_CANE);
        }
        return HARVEST_CROPS.contains(pendingBlock) && !isNotFullyGrown(state, pendingBlock);
    }

    private void resetPending() {
        pendingPos = null;
        pendingBlock = null;
        pendingWorld = null;
        useInteract = false;
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

    private int findFortuneToolSlot(LocalPlayer player) {
        Holder<Enchantment> fortuneHolder = player.level()
                .registryAccess()
                .lookupOrThrow(Registries.ENCHANTMENT)
                .getOrThrow(Enchantments.FORTUNE);

        for (int i = 0; i < 9; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (stack.isEmpty()) continue;

            if (isHarvestTool(stack)) {
                ItemEnchantments enchantments =
                        stack.getOrDefault(DataComponents.ENCHANTMENTS, ItemEnchantments.EMPTY);

                int fortuneLevel = enchantments.getLevel(fortuneHolder);
                if (fortuneLevel >= 1) {
                    return i;
                }
            }
        }
        return -1;
    }


    private boolean isHarvestTool(ItemStack stack) {
        return stack.is(ItemTags.AXES) ||
                stack.is(ItemTags.SHOVELS) ||
                stack.is(ItemTags.HOES) ||
                stack.is(ItemTags.PICKAXES);
    }

    private boolean hasSword(LocalPlayer player) {
        if (player.getMainHandItem().is(ItemTags.SWORDS)) return true;
        for (int i = 0; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (!stack.isEmpty() && stack.is(ItemTags.SWORDS)) {
                return true;
            }
        }
        return false;
    }

    private void ensureSword(LocalPlayer player) {
        if (player.getMainHandItem().is(ItemTags.SWORDS)) return;

        for (int i = 0; i < 9; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (!stack.isEmpty() && stack.is(ItemTags.SWORDS)) {
                player.getInventory().setSelectedSlot(i);
                return;
            }
        }

        for (int i = 9; i < 36; i++) {
            ItemStack stack = player.getInventory().getItem(i);
            if (!stack.isEmpty() && stack.is(ItemTags.SWORDS)) {
                moveToHotbar(player, i);
                return;
            }
        }
    }

    private void moveToHotbar(LocalPlayer player, int sourceSlot) {
        int hotbarSlot = -1;
        for (int i = 0; i < 9; i++) {
            if (player.getInventory().getItem(i).isEmpty()) {
                hotbarSlot = i;
                break;
            }
        }
        if (hotbarSlot == -1) hotbarSlot = player.getInventory().getSelectedSlot();

        var handler = player.containerMenu;
        clickSlot(handler, sourceSlot);
        clickSlot(handler, hotbarSlot + 36);
        if (!handler.getCarried().isEmpty()) {
            clickSlot(handler, sourceSlot);
        }
        player.getInventory().setSelectedSlot(hotbarSlot);
    }

    private void clickSlot(AbstractContainerMenu handler, int slotIndex) {
        Minecraft client = Minecraft.getInstance();
        if (client.player == null) return;
        if (client.gameMode != null) {
            client.gameMode.handleContainerInput(
                    handler.containerId,
                    slotIndex,
                    0,
                    ContainerInput.PICKUP,
                    client.player
            );
        }
    }

    @Override
    public String getName() {
        return Component.translatable("autoharvest.mode.harvest").getString();
    }

    @Override
    public void onDisable() {
        scanCursor.reset();
        resetPending();
    }
}
