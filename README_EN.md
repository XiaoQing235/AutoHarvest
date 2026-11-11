[**中文版描述**](README.md)
# AutoHarvest

An automatic farming mod for Minecraft.

> ⚠️ **Note**: Due to limited time, new features and content are only added to the **latest version**. Older versions receive bug fixes only and will not get new features.

## Usage

- Press **`H`** to toggle the mod on or off.
- **Plant mode** is enabled by default.

## Mode Overview


| Mode              | Command                      | Description                                                                                          |
|-------------------|------------------------------|------------------------------------------------------------------------------------------------------|
| **Plant Mode**    | `/autoharvest mode plant`    | Automatically plants crops such as wheat seeds and carrots on empty farmland.                        |
| **Harvest Mode**  | `/autoharvest mode harvest`  | Automatically harvests mature crops.                                                                 |
| **Weed Mode**     | `/autoharvest mode weed`     | Automatically removes weeds such as grass and tall grass from farmland.                              |
| **Feed Mode**     | `/autoharvest mode feed`     | Automatically feeds breedable animals to trigger breeding.                                           |
| **Hoe Mode**      | `/autoharvest mode hoe`      | Automatically turns grass blocks or dirt near water into farmland.                                   |
| **Fishing Mode**  | `/autoharvest mode fishing`  | Automatically casts and retracts the fishing rod for fully automated fishing.                        |
| **Bonemeal Mode** | `/autoharvest mode bonemeal` | Automatically applies bone meal to immature crops to accelerate growth.                              |
| **Farmer Mode**   | `/autoharvest mode farmer`   | Combines harvesting and planting: automatically harvests mature crops and replants them immediately. |

> 💡 **Tip**: After switching modes, the mod will automatically be **enabled** (press `H` to toggle it on or off).

## 26.2 branch settings

- **Use player interaction range (`rangeSource`)** is a boolean toggle, default `false`. `false` uses `radiusCenti` from the config file (10–65, or 1–6.5 blocks). `true` reads the player's current range attributes: `blockInteractionRange()` for blocks and `entityInteractionRange()` for feeding/shearing, including modifiers. The enabled setting uses vanilla reach checks without applying the custom radius or a hidden reach cap. Server rules still apply. Legacy `CUSTOM`/`PLAYER_ATTRIBUTE` values migrate automatically to `false`/`true`, preserving the existing radius and all other settings.
- **Maximum actions per active tick (`maxActionsPerTick`)** is 1–64, default 1. `ticksPerAction` still controls the interval between batches. Bounded scanning processes distinct targets and counts dispatched attempts, not server-confirmed successes. Farmer harvesting and replanting share this budget (with the default 1, they run on separate ticks). Inventory refill/switching is not a world action. Fortune-tool switching still waits until the next scheduled invocation. Fishing's state machine and timing are unchanged.
- **Swing hand (`swingHand`)** defaults to false. When enabled, successful client-side interactions use the vanilla swing for the actual hand, normally visible to other players. No extra custom swing packets are sent. Server-triggered animations cannot be suppressed. Feeding's former unconditional swing now follows this setting too.

### Performance and validation

Block scanning avoids per-position center-vector allocations; hoe mode no longer scans twice; water checks reuse a mutable position and the fetched block state, including upstream a92220ec's fix to inspect water on the same layer and one layer above. All radii retain scan progress so the nearest unchanged target cannot consume every action batch. A completed sweep can wrap within the same invocation without inserting an idle tick. Large ranges also use a small live-centered discovery pass and up to 256 remembered action targets, avoiding long action gaps while the broad sweep traverses empty outer shells. The broad sweep always advances first; known targets retry in round-robin order after local discovery. Targets are revalidated against current state, selection range and player reach before use, with no duplicate dispatch to a scan position within one invocation. All three phases together inspect at most 4,096 positions, including raw cube visits outside the sphere; the configured range is not reduced. Ordinary movement retains broad scan progress; relocation beyond the scan diameter, world changes and range changes reset it. Remembered targets are not server-confirmed successes: server latency, rejection and the existing action interval still affect gameplay. Farmer replant tracking has size, retry and expiry limits. Newly observed crops are watched for 40 game ticks so a rollback to air can be retried; this is a finite prediction grace period, not server confirmation. Unfinished replant jobs expire after 1,200 ticks, and a full 512-entry queue pauses new seed-bearing harvests.

Merged this fork's `fix/flowing-water-26.2` fixes (`fac8a315`, `a004328`): hoe mode accepts still and flowing water within four blocks horizontally, on the same layer or one layer above. Sugar-cane adjacency follows vanilla support tags, including flowing water, waterlogged blocks and default-tag frosted ice (not ordinary ice). Each scan checks current water state, retaining mutable-position and block-state reuse.

Standalone regression checks require Python 3 and JDK 21+ and do not invoke Gradle:

```bash
python scripts/test_scans.py
python scripts/test_interactions.py
python scripts/test_water.py
```

The scan harness uses Manhattan-distance traversal with a reused mutable position. It covers ordinary-range fairness, large-range continuity, new targets while walking, cycle boundaries, batch deduplication and bounded work. Interaction checks verify that dispatched target coordinates do not change when the scan cursor moves.

Config migration checks additionally need an existing Gson JAR: `python scripts/test_config.py /path/to/gson.jar`. They use real Gson to verify legacy enum migration, boolean save/reload, preservation of other settings, and switching block/entity distance sources.

These checks use minimal API stubs and do not validate real Minecraft API compatibility or gameplay. No Gradle build/compile was run, as required by `AGENTS.md`. Fabric/NeoForge builds and client/multiplayer testing remain manual. Start with one action and increase gradually, following the server's rules.
