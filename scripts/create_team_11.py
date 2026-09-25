"""Script to generate 'Team 1.1' from the V1.1 engine and backfill GW1-5 decisions and scores."""

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fpl_manager.decision_log import record_actual_gameweek_score, record_gameweek_decision
from fpl_manager.lineup import select_starting_lineup
from fpl_manager.live_matchday import compute_matchday_lineup_performance
from fpl_manager.squad_state import CurrentSquadState, load_current_squad, save_current_squad
from fpl_manager.storage import SnapshotStore
from fpl_manager.suggest_transfers import suggest_initial_squad, suggest_transfers
from fpl_manager.teams import sync_squad_with_current_gameweek
from fpl_manager.transfers import execute_transfers

DATABASE_PATH = PROJECT_ROOT / "data" / "fpl.sqlite3"
CONFIG_DIR = PROJECT_ROOT / "config"
TEAM_ID = "team-1-1"
TEAM_DIR = CONFIG_DIR / "teams" / TEAM_ID


def main() -> None:
    TEAM_DIR.mkdir(parents=True, exist_ok=True)
    meta_file = TEAM_DIR / "metadata.json"
    meta = {
        "team_id": TEAM_ID,
        "name": "Team 1.1",
        "manager": "Marco",
        "fpl_team_id": None,
        "created_at": "2026-09-24T12:00:00.000000+00:00",
    }
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    squad_file = TEAM_DIR / "squad.json"

    print("==================================================")
    print("  Generating Team 1.1 with V1.1 Strategic Engine")
    print("==================================================")

    # Clean existing decisions for TEAM_ID from database
    store = SnapshotStore(DATABASE_PATH)
    with store._connect() as conn, conn:
        conn.execute("DELETE FROM decisions WHERE team_id = ?", (TEAM_ID,))
        conn.execute("DELETE FROM decision_recommendations WHERE decision_id NOT IN (SELECT id FROM decisions)")

    # 1. Suggest Ideal Initial Squad for Gameweek 1
    print("\n1. Generating ideal initial squad from V1.1 engine...")
    init_res = suggest_initial_squad(
        budget_millions=100.0,
        num_gameweeks=5,
        strategy="balanced",
        database_path=DATABASE_PATH,
    )
    cand = init_res["selected_candidate"]
    starters_cand = cand["starters"]
    bench_cand = cand["bench"]
    all_players = starters_cand + bench_cand
    purchase_prices = {p["id"]: p["price_tenths"] for p in all_players}

    init_state = CurrentSquadState(
        player_ids=tuple(cand["player_ids"]),
        purchase_prices_tenths=purchase_prices,
        bank_tenths=cand["bank_remaining_tenths"],
        free_transfers=1,
        chips_remaining=["wildcard", "free_hit", "bench_boost", "triple_captain"],
        season="2026/27",
        gameweek=1,
    )
    save_current_squad(squad_file, init_state)
    print(f"Initial squad saved to {squad_file}")
    print(f"Cost: {cand['total_cost_fmt']}, Bank: {cand['bank_remaining_fmt']}")

    total_season_points = 0
    current_free_transfers = 1

    # 2. Sequential Gameweek Progression (GW1 to GW5)
    for gw in range(1, 6):
        print(f"\n--- Processing Gameweek {gw} ---")
        curr_state = load_current_squad(squad_file)
        # Ensure squad state reflects current gameweek and free transfers
        curr_state = CurrentSquadState(
            player_ids=curr_state.player_ids,
            purchase_prices_tenths=curr_state.purchase_prices_tenths,
            bank_tenths=curr_state.bank_tenths,
            free_transfers=current_free_transfers,
            chips_remaining=curr_state.chips_remaining,
            season=curr_state.season,
            gameweek=gw,
        )
        save_current_squad(squad_file, curr_state)

        tx_records = []
        hits = 0

        if gw > 1:
            # Check suggested transfers using V1.1 optimization
            tx_res = suggest_transfers(
                num_transfers=1,
                squad_path=squad_file,
                database_path=DATABASE_PATH,
                gameweek=gw,
            )
            top = tx_res.get("top_suggestions", [])
            if top and (top[0].get("score", 0) > 0 or top[0].get("xp_delta", 0) > 0):
                best = top[0]
                m_out = best["outgoing"][0]["id"]
                m_in = best["incoming"][0]["id"]
                out_name = best["outgoing"][0]["name"]
                in_name = best["incoming"][0]["name"]
                print(f"  Suggested Trade: OUT {out_name} -> IN {in_name} (xp_gain: +{best.get('xp_delta', 0):.2f})")
                exec_res = execute_transfers(
                    squad_path=squad_file,
                    transfers=[{"outgoing_id": m_out, "incoming_id": m_in}],
                    database_path=DATABASE_PATH,
                    gameweek=gw,
                )
                tx_records = exec_res["transfers"]
                hits = exec_res["transfer_hits"]
                print(f"  Executed 1 transfer. Bank after: {exec_res['bank_fmt']}")
                current_free_transfers = 1
            else:
                print(f"  Rolling free transfer (no positive-gain trade). FT: {current_free_transfers} -> {min(5, current_free_transfers + 1)}")
                current_free_transfers = min(5, current_free_transfers + 1)
                # Update squad file with rolled free transfer
                saved_st = load_current_squad(squad_file)
                save_current_squad(
                    squad_file,
                    CurrentSquadState(
                        player_ids=saved_st.player_ids,
                        purchase_prices_tenths=saved_st.purchase_prices_tenths,
                        bank_tenths=saved_st.bank_tenths,
                        free_transfers=current_free_transfers,
                        chips_remaining=saved_st.chips_remaining,
                        season=saved_st.season,
                        gameweek=gw,
                    )
                )

        # Select optimal Starting XI, captain, and bench
        lineup = select_starting_lineup(
            squad_path=squad_file,
            database_path=DATABASE_PATH,
            gameweek=gw,
        )
        starting_ids = [p["id"] for p in lineup["starters"]]
        bench_ids = [p["id"] for p in lineup["bench"]]
        cap_id = lineup["captain"]["id"]
        vc_id = lineup["vice_captain"]["id"]
        cap_name = lineup["captain"]["name"]
        vc_name = lineup["vice_captain"]["name"]

        # Record decision in immutable audit log
        dec = record_gameweek_decision(
            gameweek=gw,
            squad_player_ids=starting_ids + bench_ids,
            starting_player_ids=starting_ids,
            bench_player_ids=bench_ids,
            captain_id=cap_id,
            vice_captain_id=vc_id,
            team_id=TEAM_ID,
            season="2026/27",
            transfers=tx_records,
            transfer_hits=hits,
            chip_played=None,
            notes=f"Team 1.1 Gameweek {gw} Decision (V1.1 Engine)",
            database_path=DATABASE_PATH,
            overwrite=True,
        )

        # Compute matchday points and autosubs
        perf = compute_matchday_lineup_performance(
            gameweek=gw,
            starting_ids=starting_ids,
            bench_ids=bench_ids,
            captain_id=cap_id,
            vice_captain_id=vc_id,
            transfer_hits=hits,
            database_path=DATABASE_PATH,
        )
        net_pts = perf["net_points"]
        total_season_points += net_pts

        # Record actual points in SQLite
        record_actual_gameweek_score(
            gameweek=gw,
            actual_points=net_pts,
            team_id=TEAM_ID,
            season="2026/27",
            database_path=DATABASE_PATH,
        )

        effective_cap = perf.get("captain", {}).get("name", cap_name)
        effective_cap_pts = perf.get("captain", {}).get("points", 0)
        print(f"  Lineup: {len(starting_ids)} Starters, {len(bench_ids)} Bench")
        print(f"  Captain: {cap_name} (effective in-match: {effective_cap} = {effective_cap_pts} pts)")
        if perf.get("autosubs"):
            for sub in perf["autosubs"]:
                print(f"  Autosub: {sub['out']['name']} -> {sub['in']['name']} ({sub['in']['points']} pts)")
        print(f"  Actual Net Points: {net_pts} pts")

    # 3. Final synchronization to current gameweek (GW6)
    final_state = sync_squad_with_current_gameweek(
        squad_file,
        team_id=TEAM_ID,
        config_dir=CONFIG_DIR,
        database_path=DATABASE_PATH,
    )
    print("\n==================================================")
    print(f"  Team 1.1 Complete! Total Points (GW1-5): {total_season_points} pts")
    print(f"  Current Squad State: GW{final_state.gameweek}, Free Transfers: {final_state.free_transfers}, Bank: £{final_state.bank_tenths / 10:.1f}m")
    print("==================================================")


if __name__ == "__main__":
    main()
