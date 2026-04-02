"""
Rebuild progress.save for Slay The Spire 2 from history/*.run files.

Usage:
    python rebuild_progress.py [save_directory]

If save_directory is provided, reads history/ from there and writes progress.save there.
Otherwise, looks for ./history/ in the current directory.

The script auto-detects the user's Steam ID from the run files — no manual
configuration needed. In solo runs player_id is always 1; in multiplayer runs
the save owner's Steam ID appears in every run (since it's their history folder).
"""

import json
import os
import sys
from collections import defaultdict, Counter
from pathlib import Path

# All 57 epoch IDs extracted from the game files
ALL_EPOCH_IDS = [
    # Story
    "NEOW_EPOCH",
    "OROBAS_EPOCH",
    "DARV_EPOCH",
    "UNDERDOCKS_EPOCH",
    "ACT2_B_EPOCH",
    "ACT3_B_EPOCH",
    # Ironclad (no IRONCLAD1 — starter character)
    "IRONCLAD2_EPOCH",
    "IRONCLAD3_EPOCH",
    "IRONCLAD4_EPOCH",
    "IRONCLAD5_EPOCH",
    "IRONCLAD6_EPOCH",
    "IRONCLAD7_EPOCH",
    # Silent
    "SILENT1_EPOCH",
    "SILENT2_EPOCH",
    "SILENT3_EPOCH",
    "SILENT4_EPOCH",
    "SILENT5_EPOCH",
    "SILENT6_EPOCH",
    "SILENT7_EPOCH",
    # Defect
    "DEFECT1_EPOCH",
    "DEFECT2_EPOCH",
    "DEFECT3_EPOCH",
    "DEFECT4_EPOCH",
    "DEFECT5_EPOCH",
    "DEFECT6_EPOCH",
    "DEFECT7_EPOCH",
    # Necrobinder
    "NECROBINDER1_EPOCH",
    "NECROBINDER2_EPOCH",
    "NECROBINDER3_EPOCH",
    "NECROBINDER4_EPOCH",
    "NECROBINDER5_EPOCH",
    "NECROBINDER6_EPOCH",
    "NECROBINDER7_EPOCH",
    # Regent
    "REGENT1_EPOCH",
    "REGENT2_EPOCH",
    "REGENT3_EPOCH",
    "REGENT4_EPOCH",
    "REGENT5_EPOCH",
    "REGENT6_EPOCH",
    "REGENT7_EPOCH",
    # Colorless
    "COLORLESS1_EPOCH",
    "COLORLESS2_EPOCH",
    "COLORLESS3_EPOCH",
    "COLORLESS4_EPOCH",
    "COLORLESS5_EPOCH",
    # Events
    "EVENT1_EPOCH",
    "EVENT2_EPOCH",
    "EVENT3_EPOCH",
    # Relics
    "RELIC1_EPOCH",
    "RELIC2_EPOCH",
    "RELIC3_EPOCH",
    "RELIC4_EPOCH",
    "RELIC5_EPOCH",
    # Potions
    "POTION1_EPOCH",
    "POTION2_EPOCH",
    # Special
    "CUSTOM_AND_SEEDS_EPOCH",
    "DAILY_RUN_EPOCH",
]

# Maximum ascension level in the game (raise this if MegaCrit adds more)
MAX_ASCENSION = 10

# Characters that we know exist in the game
ALL_CHARACTERS = [
    "CHARACTER.IRONCLAD",
    "CHARACTER.SILENT",
    "CHARACTER.DEFECT",
    "CHARACTER.NECROBINDER",
    "CHARACTER.REGENT",
]


def load_runs(history_dir):
    """Load all .run files from the history directory."""
    runs = []
    for fn in sorted(history_dir.iterdir()):
        if fn.suffix == ".run":
            with open(fn, "r", encoding="utf-8") as f:
                data = json.load(f)
            runs.append(data)
    runs.sort(key=lambda x: x["start_time"])
    print(f"Loaded {len(runs)} runs from {history_dir}")
    return runs


def detect_user_ids(runs):
    """Auto-detect the save owner's player IDs from run history.

    Logic:
      - In solo runs (1 player), player_id is always 1.
      - In multiplayer runs (2 players), the save owner's Steam ID appears
        in EVERY multiplayer run, because these are their history files.
      - Partner IDs vary from run to run.

    Returns a set like {1, 76561198074262599}.
    If there are no multiplayer runs, returns {1}.
    """
    user_ids = {1}  # Solo runs always use id=1

    mp_runs = [r for r in runs if len(r.get("players", [])) > 1]
    if not mp_runs:
        print(f"  No multiplayer runs found. User IDs: {user_ids}")
        return user_ids

    # Find the player ID present in ALL multiplayer runs
    # Count how many MP runs each non-1 ID appears in
    id_counts = Counter()
    for run in mp_runs:
        for p in run.get("players", []):
            pid = p["id"]
            if pid != 1:
                id_counts[pid] += 1

    total_mp = len(mp_runs)
    # The owner's ID appears in every multiplayer run
    for pid, count in id_counts.most_common():
        if count == total_mp:
            user_ids.add(pid)
            break
        # If no single ID covers all runs, take the most frequent one
        # (can happen if some runs are from different periods)
        if count >= total_mp * 0.8:
            user_ids.add(pid)
            break

    # Fallback: if still just {1}, take the most common multiplayer ID
    if len(user_ids) == 1 and id_counts:
        most_common_id = id_counts.most_common(1)[0][0]
        user_ids.add(most_common_id)

    print(f"  Auto-detected user IDs: {user_ids}")
    print(f"    Solo ID: 1")
    if len(user_ids) > 1:
        steam_id = [x for x in user_ids if x != 1][0]
        print(f"    Multiplayer Steam ID: {steam_id} (found in {id_counts[steam_id]}/{total_mp} MP runs)")

    return user_ids


def compute_character_stats(runs, user_ids):
    """Compute per-character stats: wins, losses, streaks, fastest win, playtime, max ascension.

    IMPORTANT: Only counts stats for the USER's own characters, not partners' characters
    in multiplayer runs. The user is identified by user_ids.

    max_ascension is computed ONLY from solo (1-player) wins, because in multiplayer
    the ascension level is shared and can be unlocked on one character then played on any.
    """
    stats = {}
    for ch in ALL_CHARACTERS:
        stats[ch] = {
            "id": ch,
            "total_wins": 0,
            "total_losses": 0,
            "best_win_streak": 0,
            "current_streak": 0,
            "fastest_win_time": -1,
            "max_ascension": 0,
            "playtime": 0,
            "preferred_ascension": 0,
        }

    # Track streaks - process runs in chronological order
    current_streaks = defaultdict(int)

    for run in runs:
        win = run.get("win", False)
        abandoned = run.get("was_abandoned", False)
        asc = run.get("ascension", 0)
        run_time = run.get("run_time", 0)
        is_solo = len(run.get("players", [])) == 1

        # Only process the USER's own characters, skip partner's characters
        user_characters = []
        for p in run.get("players", []):
            if p["id"] in user_ids:
                user_characters.append(p["character"])

        for ch in user_characters:
            if ch not in stats:
                stats[ch] = {
                    "id": ch,
                    "total_wins": 0,
                    "total_losses": 0,
                    "best_win_streak": 0,
                    "current_streak": 0,
                    "fastest_win_time": -1,
                    "max_ascension": 0,
                    "playtime": 0,
                    "preferred_ascension": 0,
                }

            stats[ch]["playtime"] += run_time

            if abandoned:
                continue

            if win:
                stats[ch]["total_wins"] += 1
                current_streaks[ch] += 1
                if current_streaks[ch] > stats[ch]["best_win_streak"]:
                    stats[ch]["best_win_streak"] = current_streaks[ch]

                # max_ascension only from SOLO wins
                # Winning at ascension N unlocks ascension N+1
                unlocked = min(asc + 1, MAX_ASCENSION)
                if is_solo and unlocked > stats[ch]["max_ascension"]:
                    stats[ch]["max_ascension"] = unlocked

                if stats[ch]["fastest_win_time"] == -1 or run_time < stats[ch]["fastest_win_time"]:
                    stats[ch]["fastest_win_time"] = run_time
            else:
                stats[ch]["total_losses"] += 1
                current_streaks[ch] = 0

    # Set final current_streak values
    for ch in stats:
        stats[ch]["current_streak"] = current_streaks[ch]
        # preferred_ascension = max_ascension (what the player last reached)
        stats[ch]["preferred_ascension"] = stats[ch]["max_ascension"]

    result = []
    for ch in sorted(stats.keys()):
        s = stats[ch]
        result.append({
            "best_win_streak": s["best_win_streak"],
            "current_streak": s["current_streak"],
            "fastest_win_time": s["fastest_win_time"],
            "id": s["id"],
            "max_ascension": s["max_ascension"],
            "playtime": s["playtime"],
            "preferred_ascension": s["preferred_ascension"],
            "total_losses": s["total_losses"],
            "total_wins": s["total_wins"],
        })

    return result


def compute_ancient_stats(runs, user_ids):
    """Compute per-ancient, per-character wins/losses (only user's own characters)."""
    # ancient_id -> character -> {wins, losses}
    ancient_data = defaultdict(lambda: defaultdict(lambda: {"wins": 0, "losses": 0}))

    for run in runs:
        win = run.get("win", False)
        abandoned = run.get("was_abandoned", False)
        if abandoned:
            continue

        # Only the user's own characters
        user_chars = [p["character"] for p in run.get("players", []) if p["id"] in user_ids]

        for act_floors in run.get("map_point_history", []):
            for mp in act_floors:
                if mp.get("map_point_type") == "ancient":
                    for room in mp.get("rooms", []):
                        ancient_id = room.get("model_id", "")
                        if ancient_id.startswith("EVENT."):
                            for ch in user_chars:
                                if win:
                                    ancient_data[ancient_id][ch]["wins"] += 1
                                else:
                                    ancient_data[ancient_id][ch]["losses"] += 1

    result = []
    for ancient_id in sorted(ancient_data.keys()):
        char_stats = []
        for ch in sorted(ancient_data[ancient_id].keys()):
            d = ancient_data[ancient_id][ch]
            char_stats.append({
                "character": ch,
                "losses": d["losses"],
                "wins": d["wins"],
            })
        result.append({
            "ancient_id": ancient_id,
            "character_stats": char_stats,
        })

    return result


def compute_card_stats(runs, user_ids):
    """Compute per-card stats: times_picked, times_skipped, times_won, times_lost.

    Only counts the USER's own card choices and decks, not partners'.
    """
    card_data = defaultdict(lambda: {
        "times_picked": 0,
        "times_skipped": 0,
        "times_won": 0,
        "times_lost": 0,
    })

    for run in runs:
        win = run.get("win", False)
        abandoned = run.get("was_abandoned", False)

        # Count picks and skips from card_choices — only user's player_stats
        for act_floors in run.get("map_point_history", []):
            for mp in act_floors:
                for ps in mp.get("player_stats", []):
                    if ps.get("player_id") not in user_ids:
                        continue
                    for cc in ps.get("card_choices", []):
                        card_id = cc["card"]["id"]
                        if cc.get("was_picked", False):
                            card_data[card_id]["times_picked"] += 1
                        else:
                            card_data[card_id]["times_skipped"] += 1

        if abandoned:
            continue

        # Count wins/losses from final deck — only user's own deck
        for p in run.get("players", []):
            if p["id"] not in user_ids:
                continue
            deck_card_ids = set()
            for c in p.get("deck", []):
                deck_card_ids.add(c["id"])

            for card_id in deck_card_ids:
                if win:
                    card_data[card_id]["times_won"] += 1
                else:
                    card_data[card_id]["times_lost"] += 1

    result = []
    for card_id in sorted(card_data.keys()):
        d = card_data[card_id]
        result.append({
            "id": card_id,
            "times_lost": d["times_lost"],
            "times_picked": d["times_picked"],
            "times_skipped": d["times_skipped"],
            "times_won": d["times_won"],
        })

    return result


def compute_discovered(runs):
    """Compute all discovered acts, cards, events, relics, potions."""
    acts = set()
    cards = set()
    events = set()
    relics = set()
    potions = set()

    for run in runs:
        # Acts
        for a in run.get("acts", []):
            acts.add(a)

        # Walk map_point_history
        for act_floors in run.get("map_point_history", []):
            for mp in act_floors:
                for room in mp.get("rooms", []):
                    model_id = room.get("model_id", "")
                    if model_id.startswith("EVENT."):
                        events.add(model_id)

                for ps in mp.get("player_stats", []):
                    # Cards from choices
                    for cc in ps.get("card_choices", []):
                        cards.add(cc["card"]["id"])
                    # Cards gained (from events, etc)
                    for cg in ps.get("cards_gained", []):
                        cards.add(cg["id"])
                    # Relics from choices
                    for rc in ps.get("relic_choices", []):
                        relics.add(rc["choice"])
                    # Potions from choices
                    for pc in ps.get("potion_choices", []):
                        potions.add(pc["choice"])

        # Cards and relics from final player decks
        for p in run.get("players", []):
            for c in p.get("deck", []):
                cards.add(c["id"])
            for r in p.get("relics", []):
                relics.add(r["id"])
            for pot in p.get("potions", []):
                if isinstance(pot, dict) and "id" in pot:
                    potions.add(pot["id"])

    return {
        "acts": sorted(acts),
        "cards": sorted(cards),
        "events": sorted(events),
        "relics": sorted(relics),
        "potions": sorted(potions),
    }


def compute_epochs(runs, user_ids, char_stats):
    """
    Determine epoch unlock states based on ACTUAL game logic (decompiled from sts2.dll).

    Character epochs:
      CHAR1 = play a run as that character (non-Ironclad only)
      CHAR2 = complete Act 1 with that character
      CHAR3 = complete Act 2 with that character
      CHAR4 = complete Act 3 with that character
      CHAR5 = win Ascension 1 with that character
      CHAR6 = defeat 15 elites total with that character
      CHAR7 = defeat 15 bosses total with that character

    Special epochs:
      NEOW = complete any run
      OROBAS = play all 5 characters (win or loss)
      DARV = encounter all ancient events
      CUSTOM_AND_SEEDS = win 3+ runs total
      DAILY_RUN = win a run + have played all characters

    Agnostic epochs (colorless, relic, potion, event, act):
      Unlock in fixed order based on cumulative score thresholds.
      The game tracks current_score and TotalUnlocks (0-18).
      Score thresholds: 200,500,750,1000,1250,1500,1600,1700,
                        1800,1900,2000,2100,2200,2300,2400,2500,2500,2500
    """
    earliest_time = min(r["start_time"] for r in runs)

    # --- Gather per-character data from runs ---
    char_data = {}  # char_id -> {played, max_act, elite_kills, boss_kills, won_asc1}
    total_wins = 0
    has_daily = False
    chars_played = set()
    ancients_seen = set()

    # Track per-character ascension 1 wins
    char_won_asc1 = set()

    for run in runs:
        t = run["start_time"]
        win = run.get("win", False)
        abandoned = run.get("was_abandoned", False)
        killed_by = run.get("killed_by_encounter", "NONE.NONE")
        asc = run.get("ascension", 0)

        if run.get("game_mode") == "daily":
            has_daily = True

        for p in run.get("players", []):
            if p["id"] not in user_ids:
                continue

            ch = p["character"]
            chars_played.add(ch)

            if ch not in char_data:
                char_data[ch] = {
                    "played": True,
                    "max_act_completed": 0,
                    "elite_kills": 0,
                    "boss_kills": 0,
                    "first_play_time": t,
                }

            # CHAR5 condition: won at ascension 1
            if win and asc == 1:
                char_won_asc1.add(ch)

        # Count user's characters in this run
        user_chars = [p["character"] for p in run.get("players", []) if p["id"] in user_ids]
        if not user_chars:
            continue

        if win and not abandoned:
            total_wins += 1

        # Walk map_point_history
        acts_in_run = run.get("map_point_history", [])

        for act_idx, act_floors in enumerate(acts_in_run):
            act_has_boss_room = False

            for mp in act_floors:
                # Track ancient events
                if mp.get("map_point_type") == "ancient":
                    for room in mp.get("rooms", []):
                        mid = room.get("model_id", "")
                        if mid.startswith("EVENT."):
                            ancients_seen.add(mid)

                for room in mp.get("rooms", []):
                    rt = room.get("room_type", "")
                    model_id = room.get("model_id", "")

                    if rt == "elite":
                        if model_id != killed_by or win:
                            for ch in user_chars:
                                if ch in char_data:
                                    char_data[ch]["elite_kills"] += 1

                    elif rt == "boss":
                        act_has_boss_room = True
                        if model_id != killed_by or win:
                            for ch in user_chars:
                                if ch in char_data:
                                    char_data[ch]["boss_kills"] += 1

            # Act completed if boss was defeated
            if act_has_boss_room:
                last_room = None
                for mp in act_floors:
                    for room in mp.get("rooms", []):
                        last_room = room

                act_completed = win or (last_room and last_room.get("model_id") != killed_by)
                if act_completed:
                    act_num = act_idx + 1
                    for ch in user_chars:
                        if ch in char_data:
                            if act_num > char_data[ch]["max_act_completed"]:
                                char_data[ch]["max_act_completed"] = act_num

    # --- Build epoch unlock map ---
    epoch_map = {}

    char_prefix = {
        "CHARACTER.IRONCLAD": "IRONCLAD",
        "CHARACTER.SILENT": "SILENT",
        "CHARACTER.DEFECT": "DEFECT",
        "CHARACTER.NECROBINDER": "NECROBINDER",
        "CHARACTER.REGENT": "REGENT",
    }

    for char_id, prefix in char_prefix.items():
        cd = char_data.get(char_id)
        if not cd:
            continue

        t = cd["first_play_time"]
        start = 2 if prefix == "IRONCLAD" else 1

        # CHAR1: played the character (non-Ironclad)
        if start == 1 and cd["played"]:
            epoch_map[f"{prefix}1_EPOCH"] = t

        # CHAR2: completed Act 1
        if cd["max_act_completed"] >= 1:
            epoch_map[f"{prefix}2_EPOCH"] = t

        # CHAR3: completed Act 2
        if cd["max_act_completed"] >= 2:
            epoch_map[f"{prefix}3_EPOCH"] = t

        # CHAR4: completed Act 3
        if cd["max_act_completed"] >= 3:
            epoch_map[f"{prefix}4_EPOCH"] = t

        # CHAR5: won Ascension 1 with this character
        if char_id in char_won_asc1:
            epoch_map[f"{prefix}5_EPOCH"] = t

        # CHAR6: 15+ elites defeated with this character
        if cd["elite_kills"] >= 15:
            epoch_map[f"{prefix}6_EPOCH"] = t

        # CHAR7: 15+ bosses defeated with this character
        if cd["boss_kills"] >= 15:
            epoch_map[f"{prefix}7_EPOCH"] = t

    # --- Special epochs ---

    # NEOW: always (completed any run)
    epoch_map["NEOW_EPOCH"] = earliest_time

    # OROBAS: played all 5 characters
    if len(chars_played) >= len(ALL_CHARACTERS):
        epoch_map["OROBAS_EPOCH"] = earliest_time

    # DARV: encountered all ancient events
    # Known ancients from game data: NEOW, OROBAS, DARV, PAEL, TEZCATARA, TANX, NONUPEIPE, VAKUU
    ALL_ANCIENTS = {"EVENT.NEOW", "EVENT.OROBAS", "EVENT.DARV", "EVENT.PAEL",
                    "EVENT.TEZCATARA", "EVENT.TANX", "EVENT.NONUPEIPE", "EVENT.VAKUU"}
    if ALL_ANCIENTS.issubset(ancients_seen):
        epoch_map["DARV_EPOCH"] = earliest_time

    # CUSTOM_AND_SEEDS: 3+ total wins
    if total_wins >= 3:
        epoch_map["CUSTOM_AND_SEEDS_EPOCH"] = earliest_time

    # DAILY_RUN: won a run + played all characters
    if total_wins >= 1 and len(chars_played) >= len(ALL_CHARACTERS):
        epoch_map["DAILY_RUN_EPOCH"] = earliest_time

    # --- Agnostic epochs: unlock via cumulative score thresholds ---
    # The game adds run score to current_score after each run.
    # When current_score >= threshold, an agnostic epoch unlocks and
    # current_score -= threshold. TotalUnlocks increments by 1.
    #
    # We can't perfectly reconstruct current_score from history (score isn't
    # stored in .run files), but we CAN count TotalUnlocks from the progress
    # save or estimate from the number of runs played.
    #
    # Thresholds: 200,500,750,1000,1250,1500,1600,1700,1800,1900,
    #             2000,2100,2200,2300,2400,2500,2500,2500
    # Total needed for all 18: ~31,150 points
    #
    # Since we can't compute exact score, we set total_unlocks based on
    # progress.save template if available, otherwise estimate conservatively.

    AGNOSTIC_ORDER = [
        "COLORLESS1_EPOCH",   # threshold: 200
        "RELIC1_EPOCH",       # 500
        "POTION1_EPOCH",      # 750
        "UNDERDOCKS_EPOCH",   # 1000
        "COLORLESS2_EPOCH",   # 1250
        "RELIC2_EPOCH",       # 1500
        "POTION2_EPOCH",      # 1600
        "ACT2_B_EPOCH",       # 1700
        "COLORLESS3_EPOCH",   # 1800
        "RELIC3_EPOCH",       # 1900
        "ACT3_B_EPOCH",       # 2000
        "COLORLESS4_EPOCH",   # 2100
        "RELIC4_EPOCH",       # 2200
        "EVENT1_EPOCH",       # 2300
        "COLORLESS5_EPOCH",   # 2400
        "RELIC5_EPOCH",       # 2500
        "EVENT2_EPOCH",       # 2500
        "EVENT3_EPOCH",       # 2500
    ]

    SCORE_THRESHOLDS = [200, 500, 750, 1000, 1250, 1500, 1600, 1700,
                        1800, 1900, 2000, 2100, 2200, 2300, 2400, 2500, 2500, 2500]

    # Compute exact score using the game's formula (from ScoreUtility.CalculateScore):
    #   base = sum(floors_in_act * 10 * act_number) for each act
    #   bonus = 300 if win, 200 if reached act 3+, 100 if reached act 2, else 0
    #   score = int(base + bonus) * (1.0 + ascension * 0.1))
    estimated_score = 0
    for run in runs:
        if run.get("was_abandoned"):
            continue
        acts = run.get("map_point_history", [])
        base = 0
        for act_idx, act_floors in enumerate(acts):
            base += len(act_floors) * 10 * (act_idx + 1)
        if run.get("win"):
            base += 300
        elif len(acts) > 2:
            base += 200
        elif len(acts) == 2:
            base += 100
        asc = run.get("ascension", 0)
        estimated_score += int(base * (1.0 + asc * 0.1))

    # Simulate the unlock process
    total_unlocks = 0
    remaining_score = estimated_score
    for i, threshold in enumerate(SCORE_THRESHOLDS):
        if remaining_score >= threshold:
            remaining_score -= threshold
            total_unlocks += 1
        else:
            break

    for i, eid in enumerate(AGNOSTIC_ORDER):
        if i < total_unlocks:
            epoch_map[eid] = earliest_time

    # --- Build result ---
    # Also compute total_unlocks for the progress save field
    result = []
    for eid in ALL_EPOCH_IDS:
        t = epoch_map.get(eid, 0)
        if t and t > 0:
            result.append({
                "id": eid,
                "obtain_date": t,
                "state": "revealed",
            })
        else:
            result.append({
                "id": eid,
                "obtain_date": 0,
                "state": "not_obtained",
            })

    return result, total_unlocks


def compute_floors_climbed(runs):
    """Total map points visited across all runs."""
    total = 0
    for run in runs:
        for act_floors in run.get("map_point_history", []):
            total += len(act_floors)
    return total


def compute_total_playtime(runs):
    """Sum of all run times."""
    return sum(r.get("run_time", 0) for r in runs)


def compute_max_multiplayer_ascension(runs):
    """Max ascension unlocked in multiplayer runs (winning at N unlocks N+1)."""
    max_asc = 0
    for run in runs:
        if len(run.get("players", [])) > 1 and run.get("win", False):
            asc = run.get("ascension", 0)
            unlocked = min(asc + 1, MAX_ASCENSION)
            if unlocked > max_asc:
                max_asc = unlocked
    return max_asc


def load_template(save_dir):
    """Try to load an existing progress.save as a template for unique_id/schema_version."""
    for name in ["progress.save.broken", "progress.save"]:
        path = save_dir / name
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception:
                continue
    return None


def build_progress(runs, user_ids, save_dir):
    """Build the full progress.save JSON from run history."""
    template = load_template(save_dir)

    char_stats = compute_character_stats(runs, user_ids)
    ancient_stats = compute_ancient_stats(runs, user_ids)
    card_stats = compute_card_stats(runs, user_ids)
    discovered = compute_discovered(runs)
    epochs, agnostic_unlocks = compute_epochs(runs, user_ids, char_stats)
    floors = compute_floors_climbed(runs)
    total_playtime = compute_total_playtime(runs)
    max_mp_asc = compute_max_multiplayer_ascension(runs)

    # Use template values for fields we can't derive, or sensible defaults
    unique_id = template["unique_id"] if template else "PLAYER"
    schema_version = template["schema_version"] if template else 21

    progress = {
        "ancient_stats": ancient_stats,
        "architect_damage": 0,
        "card_stats": card_stats,
        "character_stats": char_stats,
        "current_score": 0,
        "discovered_acts": discovered["acts"],
        "discovered_cards": discovered["cards"],
        "discovered_events": discovered["events"],
        "discovered_potions": discovered["potions"],
        "discovered_relics": discovered["relics"],
        "enable_ftues": False,  # User has played 100+ runs, no need for tutorials
        "encounter_stats": [],
        "enemy_stats": [],
        "epochs": epochs,
        "floors_climbed": floors,
        "ftue_completed": [
            "multiplayer_warning",
        ],
        "max_multiplayer_ascension": max_mp_asc,
        "pending_character_unlock": "NONE.NONE",
        "preferred_multiplayer_ascension": 0,
        "schema_version": schema_version,
        "test_subject_kills": 0,
        "total_playtime": total_playtime,
        "total_unlocks": agnostic_unlocks,
        "unique_id": unique_id,
        "unlocked_achievements": [],
        "wongo_points": 0,
    }

    return progress


def print_summary(progress):
    """Print a summary of the rebuilt progress."""
    print("\n=== REBUILT PROGRESS SUMMARY ===")
    print(f"  Unique ID: {progress['unique_id']}")
    print(f"  Schema version: {progress['schema_version']}")
    print(f"  Total playtime: {progress['total_playtime']} sec ({progress['total_playtime'] // 3600}h {(progress['total_playtime'] % 3600) // 60}m)")
    print(f"  Floors climbed: {progress['floors_climbed']}")
    print(f"  Max MP ascension: {progress['max_multiplayer_ascension']}")
    print()

    print("  Character stats:")
    for cs in progress["character_stats"]:
        print(f"    {cs['id']}: {cs['total_wins']}W / {cs['total_losses']}L, "
              f"best streak={cs['best_win_streak']}, max_asc={cs['max_ascension']}, "
              f"fastest_win={'%dm' % (cs['fastest_win_time']//60) if cs['fastest_win_time'] > 0 else 'N/A'}")
    print()

    print(f"  Ancient stats: {len(progress['ancient_stats'])} ancients tracked")
    print(f"  Card stats: {len(progress['card_stats'])} cards tracked")
    print(f"  Discovered: {len(progress['discovered_acts'])} acts, "
          f"{len(progress['discovered_cards'])} cards, "
          f"{len(progress['discovered_events'])} events, "
          f"{len(progress['discovered_relics'])} relics, "
          f"{len(progress['discovered_potions'])} potions")
    print()

    print("  Epochs:")
    obtained = sum(1 for e in progress["epochs"] if e["state"] == "revealed")
    not_obtained = sum(1 for e in progress["epochs"] if e["state"] == "not_obtained")
    print(f"    {obtained} obtained, {not_obtained} not obtained")


STS2_APP_ID = "2868840"


def find_steam_dir():
    """Auto-detect Steam installation directory across platforms."""
    import platform
    system = platform.system()

    candidates = []

    if system == "Windows":
        # Try registry first
        try:
            import winreg
            for hive, subkey in [
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            ]:
                try:
                    key = winreg.OpenKey(hive, subkey)
                    val, _ = winreg.QueryValueEx(key, "SteamPath" if hive == winreg.HKEY_CURRENT_USER else "InstallPath")
                    winreg.CloseKey(key)
                    if val:
                        candidates.append(Path(val))
                except OSError:
                    pass
        except ImportError:
            pass

        # Common Windows locations
        for drive in "CDEFG":
            candidates.append(Path(f"{drive}:/Program Files (x86)/Steam"))
            candidates.append(Path(f"{drive}:/Program Files/Steam"))
            candidates.append(Path(f"{drive}:/Steam"))
            candidates.append(Path(f"{drive}:/programs"))  # custom steamapps location

    elif system == "Darwin":  # macOS
        candidates.append(Path.home() / "Library/Application Support/Steam")

    else:  # Linux
        candidates.append(Path.home() / ".steam/steam")
        candidates.append(Path.home() / ".local/share/Steam")

    for c in candidates:
        # Steam dir may have userdata directly, or under steamapps parent
        if (c / "userdata").is_dir():
            return c
        # Sometimes steamapps is a sibling — check parent
        if c.name == "steamapps" and (c.parent / "userdata").is_dir():
            return c.parent

    return None


def find_all_profiles():
    """Auto-detect all STS2 save profiles from standard OS locations.

    Returns a list of dicts: [{path, steam_id, profile_name, run_count}, ...]
    """
    import platform
    system = platform.system()

    candidates = []

    if system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidates.append(Path(appdata) / "SlayTheSpire2")
    elif system == "Darwin":
        candidates.append(Path.home() / "Library/Application Support/SlayTheSpire2")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        if xdg:
            candidates.append(Path(xdg) / "SlayTheSpire2")
        candidates.append(Path.home() / ".config/SlayTheSpire2")

    profiles = []
    for base in candidates:
        steam_dir = base / "steam"
        if not steam_dir.is_dir():
            continue
        for steam_id_dir in sorted(steam_dir.iterdir()):
            if not steam_id_dir.is_dir():
                continue
            for profile_dir in sorted(steam_id_dir.iterdir()):
                saves = profile_dir / "saves"
                history = saves / "history"
                if history.is_dir():
                    run_count = sum(1 for f in history.iterdir() if f.suffix == ".run")
                    if run_count > 0:
                        profiles.append({
                            "path": saves,
                            "steam_id": steam_id_dir.name,
                            "profile_name": profile_dir.name,
                            "run_count": run_count,
                        })

    return profiles


def choose_profile(profiles):
    """Let the user pick a profile if multiple are found. Returns save_dir Path."""
    if not profiles:
        return None

    if len(profiles) == 1:
        p = profiles[0]
        print(f"  Found 1 profile: {p['profile_name']} ({p['run_count']} runs)")
        return p["path"]

    print(f"  Found {len(profiles)} profiles:\n")
    for i, p in enumerate(profiles, 1):
        print(f"    [{i}] {p['profile_name']}  —  {p['run_count']} runs  (steam: {p['steam_id']})")
        print(f"        {p['path']}")
    print()

    while True:
        try:
            choice = input(f"  Select profile [1-{len(profiles)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(profiles):
                return profiles[idx]["path"]
        except (ValueError, EOFError):
            pass
        print(f"  Please enter a number between 1 and {len(profiles)}")


def find_steam_cloud_cache(steam_id_64):
    """Find the Steam Cloud local cache for STS2 given a SteamID64.

    Steam stores cloud cache at: <steam_dir>/userdata/<steam3_id>/<app_id>/remote/
    Steam3 ID = SteamID64 - 76561197960265728
    """
    steam_dir = find_steam_dir()
    if not steam_dir:
        return None

    steam3_id = steam_id_64 - 76561197960265728
    cache_dir = steam_dir / "userdata" / str(steam3_id) / STS2_APP_ID
    if cache_dir.is_dir():
        return cache_dir

    # Fallback: search all userdata folders for the app
    userdata = steam_dir / "userdata"
    if userdata.is_dir():
        for uid_dir in userdata.iterdir():
            app_dir = uid_dir / STS2_APP_ID
            if app_dir.is_dir():
                return app_dir

    return None


def patch_remotecache_vdf(cache_dir, progress_data_bytes, vdf_key="profile1/saves/progress.save"):
    """Update remotecache.vdf so Steam sees the new file as synced."""
    import hashlib
    import time

    vdf_path = cache_dir / "remotecache.vdf"
    if not vdf_path.exists():
        print("  [WARN] remotecache.vdf not found, skipping patch")
        return False

    sha1 = hashlib.sha1(progress_data_bytes).hexdigest()
    size = len(progress_data_bytes)
    now = str(int(time.time()))

    with open(vdf_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find and replace the progress.save block (dynamic profile name)
    import re
    escaped_key = re.escape(vdf_key)
    pattern = (
        r'("' + escaped_key + r'"\s*\{[^}]*?"size"\s+)"(\d+)"'
        r'([^}]*?"localtime"\s+)"(\d+)"'
        r'([^}]*?"time"\s+)"(\d+)"'
        r'([^}]*?"remotetime"\s+)"(\d+)"'
        r'([^}]*?"sha"\s+)"([a-f0-9]+)"'
    )
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        print("  [WARN] Could not find progress.save entry in remotecache.vdf")
        return False

    new_block = (
        f'{match.group(1)}"{size}"'
        f'{match.group(3)}"{now}"'
        f'{match.group(5)}"{now}"'
        f'{match.group(7)}"{now}"'
        f'{match.group(9)}"{sha1}"'
    )
    content = content[:match.start()] + new_block + content[match.end():]

    with open(vdf_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  Updated remotecache.vdf (size={size}, sha={sha1[:12]}...)")
    return True


def extract_steam_id_from_path(save_dir):
    """Extract SteamID64 from the save directory path.

    The path looks like: .../SlayTheSpire2/steam/<STEAM_ID>/profile1/saves
    So save_dir.parent.parent.name is the Steam ID.
    """
    try:
        # save_dir = .../steam/<STEAM_ID>/profile1/saves
        # save_dir.parent = .../steam/<STEAM_ID>/profile1
        # save_dir.parent.parent = .../steam/<STEAM_ID>
        steam_id_str = save_dir.parent.parent.name
        steam_id = int(steam_id_str)
        if steam_id > 76561197960265728:  # Valid SteamID64
            return steam_id
    except (ValueError, TypeError):
        pass
    return None


def deploy_save(progress_json, save_dir, user_ids):
    """Write progress.save to all relevant locations and patch Steam Cloud cache."""
    progress_bytes = json.dumps(progress_json, indent=2, ensure_ascii=False).encode("utf-8")

    # Extract profile name from save_dir path (e.g. .../profile1/saves -> profile1)
    profile_name = save_dir.parent.name  # saves -> profile1

    # 1. Write to save directory
    output_file = save_dir / "progress.save"
    with open(output_file, "wb") as f:
        f.write(progress_bytes)
    print(f"\n[1/3] Saved to {output_file} ({len(progress_bytes)} bytes)")

    # 2. Find Steam ID — try multiplayer detection first, then extract from path
    steam_id_64 = None
    for uid in user_ids:
        if uid != 1:
            steam_id_64 = uid
            break

    if not steam_id_64:
        steam_id_64 = extract_steam_id_from_path(save_dir)
        if steam_id_64:
            print(f"  Steam ID extracted from save path: {steam_id_64}")

    if steam_id_64:
        cache_dir = find_steam_cloud_cache(steam_id_64)
        if cache_dir:
            remote_save = cache_dir / "remote" / profile_name / "saves" / "progress.save"
            if remote_save.parent.is_dir():
                with open(remote_save, "wb") as f:
                    f.write(progress_bytes)
                print(f"[2/3] Patched Steam Cloud cache: {remote_save}")

                # Patch remotecache.vdf
                vdf_key = f"{profile_name}/saves/progress.save"
                if patch_remotecache_vdf(cache_dir, progress_bytes, vdf_key):
                    print("[3/3] Steam Cloud index updated — Steam will see files as synced")
                else:
                    print("[3/3] Could not update remotecache.vdf — you may need to disable Steam Cloud")
            else:
                print(f"[2/3] Steam Cloud remote dir not found at {remote_save.parent}")
                print("[3/3] Skipped — disable Steam Cloud manually before launching")
        else:
            print("[2/3] Steam Cloud cache not found (Steam may be installed in a non-standard location)")
            print("  Looked for: userdata/<steam3_id>/2868840/")
            print(f"  Steam3 ID would be: {steam_id_64 - 76561197960265728}")
            print("[3/3] Skipped — disable Steam Cloud manually before launching")
    else:
        print("[2/3] Could not determine Steam ID")
        print("  The save path doesn't contain a Steam ID and no multiplayer runs were found.")
        print("[3/3] Skipped — disable Steam Cloud manually before launching")
        print("[3/3] Skipped — disable Steam Cloud manually before launching")


def main():
    # Determine save directory from command line or auto-detect
    if len(sys.argv) > 1:
        save_dir = Path(sys.argv[1])
    else:
        print("Auto-detecting save profiles...")
        profiles = find_all_profiles()
        save_dir = choose_profile(profiles)
        if not save_dir:
            save_dir = Path(".")
            print(f"  No profiles found, using current directory: {save_dir.resolve()}")

    history_dir = save_dir / "history"
    if not history_dir.exists():
        print(f"\nError: {history_dir} directory not found!")
        print()
        print("Usage: python rebuild_progress.py [save_directory]")
        print()
        print("The save directory should contain a 'history/' folder with .run files.")
        print("Typical locations:")
        print("  Windows: %APPDATA%\\SlayTheSpire2\\steam\\<STEAM_ID>\\profile1\\saves")
        print("  Linux:   ~/.config/SlayTheSpire2/steam/<STEAM_ID>/profile1/saves")
        print("  macOS:   ~/Library/Application Support/SlayTheSpire2/steam/<STEAM_ID>/profile1/saves")
        sys.exit(1)

    runs = load_runs(history_dir)
    if not runs:
        print("Error: No .run files found in history/")
        sys.exit(1)

    print("\nDetecting user identity...")
    user_ids = detect_user_ids(runs)

    progress = build_progress(runs, user_ids, save_dir)
    print_summary(progress)

    deploy_save(progress, save_dir, user_ids)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Keep window open when running as exe
        if getattr(sys, "frozen", False):
            input("\nPress Enter to close...")
