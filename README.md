# STS2 Progress Rebuild

Rebuilds a corrupted `progress.save` for **Slay the Spire 2** from run history files.

After a version update or save migration failure, your `progress.save` can get wiped — losing ascension levels, card stats, epoch unlocks, and all tracked progress. However, every completed run is stored as a separate `.run` file in the `history/` folder and stays intact. This script reads all those run files and reconstructs a valid `progress.save` from scratch.

## What it restores

| Field | Source |
|---|---|
| Character stats (wins, losses, streaks, max ascension, fastest win, playtime) | Run outcomes per character |
| Card stats (times picked, skipped, won with, lost with) | Card choices & final decks |
| Ancient stats (wins/losses per ancient per character) | Ancient room encounters |
| Discovered cards, relics, potions, events, acts | Everything seen across all runs |
| All 57 epochs | Unlocked based on play history |
| Floors climbed, total playtime | Aggregated from all runs |
| Multiplayer ascension | Max ascension from co-op wins |

## Requirements

- **Python 3.7+** (no external dependencies, stdlib only)
- **Steam must be closed** when running the script (otherwise Steam locks the cloud cache files)

## Usage

### Automatic (recommended)

Just run it — the script auto-detects your save folder, Steam ID, and profile:

```bash
python rebuild_progress.py
```

If you have multiple profiles, it will ask you to choose:

```
Auto-detecting save profiles...
  Found 2 profiles:

    [1] profile1  —  112 runs  (steam: 76561198276322793)
    [2] profile2  —  2 runs    (steam: 76561198276322793)

  Select profile [1-2]:
```

### Manual path

You can pass the save directory explicitly:

```bash
python rebuild_progress.py "C:\Users\You\AppData\Roaming\SlayTheSpire2\steam\YOUR_STEAM_ID\profile1\saves"
```

## How it works

1. **Finds your saves** — scans standard OS locations for STS2 save profiles
2. **Loads all `.run` files** from `history/` and sorts them chronologically
3. **Detects your Steam ID** — in solo runs your player ID is `1`; in co-op your Steam ID appears in every multiplayer run. The script finds it automatically
4. **Rebuilds progress** — computes all stats from your run history, filtering out co-op partners' data so only YOUR character stats are tracked
5. **Deploys the save** to three locations:
   - Your game save directory (`progress.save`)
   - Steam Cloud local cache (`userdata/<id>/2868840/remote/...`)
   - Updates `remotecache.vdf` (Steam's sync index) so Steam won't overwrite your fix

## Save locations by OS

| OS | Game saves | Steam Cloud cache |
|---|---|---|
| **Windows** | `%APPDATA%\SlayTheSpire2\steam\<STEAM_ID>\profile1\saves` | `<Steam>\userdata\<STEAM3_ID>\2868840\remote` |
| **Linux** | `~/.config/SlayTheSpire2/steam/<STEAM_ID>/profile1/saves` | `~/.steam/steam/userdata/<STEAM3_ID>/2868840/remote` |
| **macOS** | `~/Library/Application Support/SlayTheSpire2/steam/<STEAM_ID>/profile1/saves` | `~/Library/Application Support/Steam/userdata/<STEAM3_ID>/2868840/remote` |

> **STEAM3_ID** = your SteamID64 minus `76561197960265728`. The script computes this automatically.

## Troubleshooting

### Steam Cloud keeps overwriting my save

The script patches both the local save and the Steam Cloud cache in one step. If it still gets overwritten:
1. Off steam-cloud for Slay the Spire 2
2. Close Steam completely
3. Run the script
4. Launch the game

If the script reports it couldn't find the Steam Cloud cache, disable cloud sync manually:
- Steam → Right-click **Slay the Spire 2** → **Properties** → **General** → uncheck **Keep game saves in the Steam Cloud**

### Wrong ascension levels

- **Ascension unlock logic**: winning at ascension N unlocks ascension N+1. The script stores `asc + 1` as your `max_ascension`. If the game has a cap (e.g. 20), it will clamp the value on load.
- **Solo only**: ascension is tracked only from **solo wins**, because in co-op the ascension level is shared and your partner's character may have reached a level you haven't unlocked solo.
- If your ascension still looks wrong, check that your run history files are complete (no missing `.run` files).

### Multiple devices (desktop + laptop, etc.)

If you play on more than one machine, Steam Cloud syncs run history between them — so all your `.run` files should already be on the last device you played on. Just run the script there.

After the script patches your save, the other devices may still have the old broken save cached. To prevent them from overwriting your fix:

1. **Run the script on one machine** (the one with the most recent history) — close Steam first
2. **On other machines** — disable Steam Cloud for STS2 before launching Steam:
   - Steam → Right-click **Slay the Spire 2** → **Properties** → **General** → uncheck **Keep game saves in the Steam Cloud**
3. Run the script on those machines too, or just copy the fixed `progress.save`
4. Re-enable Steam Cloud once all devices have the correct save

### "No .run files found"

Make sure you're pointing at the right directory. The script expects a folder with a `history/` subfolder containing `.run` files. Check the save locations table above.

## Limitations

- **`encounter_stats` / `enemy_stats`**: These fields aren't populated in the run history format, so they remain empty. The game fills them in during gameplay.
- **`wongo_points` / `architect_damage` / `test_subject_kills`**: Minor counters that can't be derived from run history. Reset to 0.
- **`unlocked_achievements`**: Steam achievements are tracked by Steam, not the save file. These stay empty but your Steam achievements are unaffected.

## License

Public domain. Use however you want.
