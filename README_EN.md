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

- **Range source (`rangeSource`)** defaults to `CUSTOM`, preserving `radiusCenti` (10–65, or 1–6.5 blocks) and existing config files. `PLAYER_ATTRIBUTE` reads the player's current `blockInteractionRange()` for blocks and `entityInteractionRange()` for feeding/shearing, including attribute modifiers. Execution uses vanilla reach checks, without applying the custom radius or a hidden reach cap. Server rules still apply.
- **Maximum actions per active tick (`maxActionsPerTick`)** is 1–64, default 1. `ticksPerAction` still controls the interval between batches. A single scan processes distinct targets and counts dispatched attempts, not server-confirmed successes. Farmer harvesting and replanting share this budget (with the default 1, they run on separate ticks). Inventory refill/switching is not a world action. Fortune-tool switching still waits until the next scheduled invocation. Fishing's state machine and timing are unchanged.
- **Swing hand (`swingHand`)** defaults to false. When enabled, successful client-side interactions use the vanilla swing for the actual hand, normally visible to other players. No extra custom swing packets are sent. Server-triggered animations cannot be suppressed. Feeding's former unconditional swing now follows this setting too.

### Performance and validation

Block scanning avoids per-position center-vector allocations; hoe mode no longer scans twice; water checks reuse a mutable position and the fetched block state. Large attribute ranges scan at most 4,096 candidate cells per invocation and resume on later active ticks. Ordinary movement retains scan progress and filters candidates against the live position. A completed sweep, a relocation beyond the scan diameter, a world change or a range change restarts it. Farmer replant tracking has size, retry and expiry limits. Newly observed crops are watched for 40 game ticks so a rollback to air can be retried; this is a finite prediction grace period, not server confirmation. Unfinished replant jobs expire after 1,200 ticks, and a full 512-entry queue pauses new seed-bearing harvests.

Standalone regression checks require Python 3 and JDK 21+ and do not invoke Gradle:

```bash
python scripts/test_scans.py
python scripts/test_interactions.py
```

These checks use minimal API stubs and do not validate real Minecraft API compatibility or gameplay. No Gradle build/compile was run, as required by `AGENTS.md`. Fabric/NeoForge builds and client/multiplayer testing remain manual. Start with one action and increase gradually, following the server's rules.
