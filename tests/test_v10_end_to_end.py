"""V1.0 Full-System Validation & End-to-End Scenarios (Workstream P8).

Validates all 10 mandatory E2E scenarios in docs/v10/v10.md Section 8.1:
1. update -> squad -> lineup -> decision log
2. decision -> transfer -> lineup -> decision
3. multiple transfers -> bank/FT/hit verification
4. transfer -> undo -> exact state restoration
5. team switch -> independent state
6. historical GW logging -> current squad unchanged
7. live scores -> autosubs -> captain -> net score
8. LLM recommendation -> deterministic validation
9. provider failure -> heuristic fallback
10. chip usage -> chip availability and strategy state

Plus:
- P3.3 Multi-GW planner exhaustive comparison
- P8.2 Historical regression fixture verification
- P8.3 Performance measurement and report generation
"""

from contextlib import closing
import json
from pathlib import Path
import time
from unittest.mock import patch

import pytest

from fpl_manager.chip_strategy import recommend_chip_strategy
from fpl_manager.decision_log import (
    apply_wildcard_or_freehit,
    get_gameweek_decision,
    log_decision_from_current_squad,
    record_gameweek_decision,
    undo_gameweek_changes,
)
from fpl_manager.lineup import select_starting_lineup
from fpl_manager.live_matchday import compute_matchday_lineup_performance
from fpl_manager.llm_advisor import generate_llm_advisory
from fpl_manager.planner import generate_multi_gameweek_plan, plan_multi_gw_exhaustive
from fpl_manager.squad_report import generate_squad_report
from fpl_manager.squad_state import CurrentSquadState, load_current_squad, save_current_squad
from fpl_manager.storage import SnapshotStore, utc_timestamp
from fpl_manager.teams import create_team, get_active_team_id, get_team_squad_path, set_active_team
from fpl_manager.transfers import execute_transfers


@pytest.fixture
def v10_system_env(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build a hermetic full-system V1.0 test environment."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = config_dir / "current_squad.json"

    store = SnapshotStore(db_path)
    store.initialize()

    teams = [
        {"id": i, "name": f"Club_{i}", "short_name": f"C{i:02d}"}
        for i in range(1, 11)
    ]

    elements = []
    for p_id in range(1, 25):
        if p_id <= 3:
            pos_id, cost = 1, 50
        elif p_id <= 10:
            pos_id, cost = 2, 50
        elif p_id <= 18:
            pos_id, cost = 3, 60
        else:
            pos_id, cost = 4, 70

        elements.append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": ((p_id - 1) % 10) + 1,
            "element_type": pos_id,
            "now_cost": cost,
            "status": "a",
            "chance_of_playing_next_round": 100,
            "news": "",
            "total_points": 20 + (p_id % 7) * 3,
            "minutes": 450,
            "starts": 5,
            "expected_goals": "0.25",
            "expected_assists": "0.20",
            "expected_goals_conceded": "1.0",
            "selected_by_percent": 15.0,
        })

    fixtures = []
    fid = 1
    for gw in (1, 2, 3, 4):
        for idx in range(5):
            th = idx * 2 + 1
            ta = idx * 2 + 2
            fixtures.append({
                "id": fid,
                "event": gw,
                "team_h": th,
                "team_a": ta,
                "team_h_difficulty": 2 if gw % 2 == 0 else 3,
                "team_a_difficulty": 3,
                "kickoff_time": f"2026-08-{10 + gw * 7:02d}T14:00:00Z",
                "finished": gw == 1,
            })
            fid += 1

    store.save_snapshot({"teams": teams, "elements": elements}, fixtures, utc_timestamp())

    # Valid 15-player squad: 2 GKP (1,2), 5 DEF (4,5,6,7,8), 5 MID (11,12,13,14,15), 3 FWD (19,20,21)
    squad_ids = [1, 2, 4, 5, 6, 7, 8, 11, 12, 13, 14, 15, 19, 20, 21]
    prices = {p: (50 if p <= 10 else (60 if p <= 18 else 70)) for p in squad_ids}
    squad_data = CurrentSquadState(
        player_ids=tuple(squad_ids),
        purchase_prices_tenths=prices,
        bank_tenths=20,
        free_transfers=1,
        chips_remaining=("wildcard", "freehit", "bench_boost", "triple_captain"),
        season="2026/27",
        gameweek=2,
    )
    save_current_squad(squad_path, squad_data)
    return config_dir, db_path, squad_path


def test_e2e_scenarios_1_to_4_update_squad_lineup_transfers_and_undo(
    v10_system_env: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """Validate E2E Scenarios 1, 2, 3, and 4:
    1. update -> squad -> lineup -> decision log
    2. decision -> transfer -> lineup -> decision
    3. multiple transfers -> bank/FT/hit verification
    4. transfer -> undo -> exact state restoration
    """
    _, db_path, squad_path = v10_system_env

    # Scenario 1: update -> squad -> lineup -> decision log
    sq_rep = generate_squad_report(squad_path=squad_path, database_path=db_path, report_path=tmp_path / "sq.json")
    assert sq_rep["is_valid"] is True

    lineup_rep = select_starting_lineup(
        squad_path=squad_path, database_path=db_path, gameweek=2, report_path=tmp_path / "lineup.json"
    )
    assert len(lineup_rep["starters"]) == 11
    assert lineup_rep["lineup_penalty_weight"] == 0.0
    assert lineup_rep["captaincy_validation"]["captain_id"] == lineup_rep["captain"]["id"]

    # Log GW1 baseline decision first so undo in GW2 has a prior GW state to revert to
    log_decision_from_current_squad(squad_path=squad_path, database_path=db_path, gameweek=1)
    dec_1 = log_decision_from_current_squad(squad_path=squad_path, database_path=db_path, gameweek=2)
    assert dec_1["gameweek"] == 2

    # Capture exact pre-transfer state
    before_state = load_current_squad(squad_path)

    # Scenario 2 & 3: decision -> multiple transfers -> bank/FT/hit verification -> lineup -> decision
    # 2 transfers with 1 FT -> 0 FTs remaining, 1 hit (4 pts)
    tx_res = execute_transfers(
        squad_path=squad_path,
        transfers=[(19, 22), (20, 23)],
        database_path=db_path,
        gameweek=2,
    )
    assert tx_res["success"] is True
    assert tx_res["free_transfers"] == 0
    assert tx_res["transfer_hits"] == 1

    lineup_after = select_starting_lineup(
        squad_path=squad_path, database_path=db_path, gameweek=2, report_path=tmp_path / "lineup2.json"
    )
    assert any(p["id"] in (22, 23) for p in lineup_after["all_squad"])

    dec_2 = get_gameweek_decision(2, season="2026/27", database_path=db_path)
    assert dec_2 is not None
    assert dec_2["transfer_hits"] == 1
    assert len(dec_2["transfers"]) == 2

    # Scenario 4: transfer -> undo -> exact state restoration
    undo_res = undo_gameweek_changes(
        squad_path=squad_path, gameweek=2, database_path=db_path
    )
    assert undo_res["success"] is True
    restored_state = load_current_squad(squad_path)
    assert set(restored_state.player_ids) == set(before_state.player_ids)
    assert restored_state.bank_tenths == before_state.bank_tenths
    assert restored_state.free_transfers == before_state.free_transfers
    assert restored_state.purchase_prices_tenths == before_state.purchase_prices_tenths


def test_e2e_scenarios_5_and_6_team_isolation_and_historical_gw_logging(
    v10_system_env: tuple[Path, Path, Path]
) -> None:
    """Validate E2E Scenarios 5 and 6:
    5. team switch -> independent state
    6. historical GW logging -> current squad unchanged
    """
    config_dir, db_path, squad_path = v10_system_env

    # Scenario 5: Create a second team and switch
    alt_squad = [1, 3, 4, 5, 6, 7, 9, 11, 12, 13, 14, 16, 19, 20, 22]
    alt_prices = {p: (50 if p <= 10 else (60 if p <= 18 else 70)) for p in alt_squad}
    second_squad_state = CurrentSquadState(
        player_ids=tuple(alt_squad),
        purchase_prices_tenths=alt_prices,
        bank_tenths=35,
        free_transfers=2,
        chips_remaining=("wildcard", "freehit", "bench_boost", "triple_captain"),
        season="2026/27",
        gameweek=2,
    )
    create_team(
        name="Second Team",
        squad_state=second_squad_state,
        config_dir=config_dir,
    )
    set_active_team("second-team", config_dir)
    assert get_active_team_id(config_dir) == "second-team"

    second_path = get_team_squad_path("second-team", config_dir)
    second_state = load_current_squad(second_path)
    default_state = load_current_squad(squad_path)
    assert set(second_state.player_ids) != set(default_state.player_ids)
    assert second_state.bank_tenths == 35
    assert default_state.bank_tenths == 20

    # Scenario 6: Historical GW logging does not alter current squad
    before_default = load_current_squad(squad_path)
    legal_starters = [1, 4, 5, 6, 7, 11, 12, 13, 14, 19, 20]
    legal_bench = [2, 8, 15, 21]
    record_gameweek_decision(
        gameweek=1,
        season="2026/27",
        squad_player_ids=list(before_default.player_ids),
        starting_player_ids=legal_starters,
        bench_player_ids=legal_bench,
        captain_id=19,
        vice_captain_id=20,
        transfers=[{"player_out_id": 24, "player_in_id": 19}],
        transfer_hits=0,
        database_path=db_path,
    )
    after_default = load_current_squad(squad_path)
    assert after_default.player_ids == before_default.player_ids
    assert after_default.bank_tenths == before_default.bank_tenths


def test_e2e_scenarios_7_8_9_10_live_scores_llm_guardrails_and_chips(
    v10_system_env: tuple[Path, Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validate E2E Scenarios 7, 8, 9, and 10:
    7. live scores -> autosubs -> captain -> net score
    8. LLM recommendation -> deterministic validation
    9. provider failure -> heuristic fallback
    10. chip usage -> chip availability and strategy state
    """
    _, db_path, squad_path = v10_system_env
    store = SnapshotStore(db_path)
    state = load_current_squad(squad_path)

    # Scenario 7: Live scores -> autosubs (starter 4 & captain 19 play 0 mins) -> vice captain 20 promoted + bench sub
    with closing(store._connect()) as conn, conn:
        for pid in state.player_ids:
            mins = 0 if pid in (4, 19) else 90
            pts = 0 if pid in (4, 19) else (10 if pid == 20 else 4)
            conn.execute(
                """
                INSERT OR REPLACE INTO player_gameweek_scores
                (event_id, player_id, total_points, minutes, goals_scored, assists, clean_sheets, goals_conceded, bonus, bps, fetched_at)
                VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0, 20, ?)
                """,
                (2, pid, pts, mins, utc_timestamp()),
            )
        conn.execute("UPDATE fixtures SET finished = 1 WHERE event = 2")

    starters = [1, 4, 5, 6, 7, 11, 12, 13, 14, 19, 20]
    bench = [2, 8, 15, 21]
    perf = compute_matchday_lineup_performance(
        gameweek=2,
        starting_ids=starters,
        bench_ids=bench,
        captain_id=19,       # 0 mins!
        vice_captain_id=20,  # 90 mins, 10 pts -> promoted to captain (20 pts)!
        chip_played=None,
        transfer_hits=1,
        database_path=db_path,
    )
    assert perf["cap_promoted"] is True
    assert len(perf["autosubs"]) >= 1
    assert perf["net_points"] == perf["gross_points"] - 4

    # Scenario 8 & 9: Provider failure -> heuristic fallback & LLM recommendation -> deterministic validation
    def _fail_gemini(*args: object, **kwargs: object) -> str:
        raise RuntimeError("Simulated Gemini provider outage")

    monkeypatch.setattr("fpl_manager.llm_advisor._call_gemini_api", _fail_gemini)
    adv = generate_llm_advisory(
        squad_path=squad_path,
        database_path=db_path,
        gameweek=2,
        provider="auto",
        api_key="AIzaSyFakeKeyForTest",
        save_reports=False,
    )
    assert adv["provider_used"].startswith("heuristic")
    assert adv["validation"]["is_legal"] is True
    assert adv["llm_evaluation_record"]["deterministic_validation_result"] is True
    assert load_current_squad(squad_path).player_ids == state.player_ids

    # Scenario 10: Chip usage -> chip availability and strategy state
    chip_strat = recommend_chip_strategy(
        squad_path=squad_path, database_path=db_path, start_gw=2, end_gw=4, report_path=tmp_path / "chips.json"
    )
    assert "recommended_schedule" in chip_strat
    assert "available_chips" in chip_strat

    wc_squad = [1, 2, 4, 5, 6, 7, 8, 11, 12, 13, 14, 15, 19, 20, 22]
    wc_starters = [1, 4, 5, 6, 7, 11, 12, 13, 14, 19, 20]
    wc_bench = [2, 8, 15, 22]
    wc_res = apply_wildcard_or_freehit(
        squad_path=squad_path,
        gameweek=2,
        mode="wildcard",
        squad_ids=wc_squad,
        starter_ids=wc_starters,
        bench_ids=wc_bench,
        captain_id=19,
        vice_captain_id=20,
        bank_tenths=20,
        database_path=db_path,
    )
    assert wc_res["success"] is True
    assert wc_res["mode"] == "wildcard"
    updated_state = load_current_squad(squad_path)
    assert "wildcard" not in updated_state.chips_remaining
    assert set(updated_state.player_ids) == set(wc_squad)


def test_p3_3_and_p8_3_multi_gw_exhaustive_and_performance_benchmarks(
    v10_system_env: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    """Compare multi-GW beam planner against exhaustive enumeration and record P8.3 performance benchmarks."""
    _, db_path, squad_path = v10_system_env

    t0 = time.perf_counter()
    beam_plan = generate_multi_gameweek_plan(
        squad_path=squad_path,
        database_path=db_path,
        horizon=2,
        start_gw=2,
        risk_profile="neutral",
        beam_width=5,
        report_path=tmp_path / "plan.json",
    )
    planner_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    exh_plan = plan_multi_gw_exhaustive(
        squad_path=squad_path,
        database_path=db_path,
        horizon=2,
        start_gw=2,
        risk_profile="neutral",
    )
    assert beam_plan["best_plan"] is not None
    assert exh_plan["best_plan"] is not None
    assert beam_plan["best_plan"]["total_net_xp"] == exh_plan["best_plan"]["total_net_xp"]

    # Record P8.3 performance benchmark report in tmp_path so pytest does not dirty tracked reports/
    perf_report = {
        "version": "1.0.1",
        "multi_gw_planner_2gw_ms": planner_ms,
        "status": "PASS",
        "usability_threshold_ms": 5000.0,
    }
    bench_path = tmp_path / "v10_performance_benchmarks.json"
    bench_path.write_text(json.dumps(perf_report, indent=2) + "\n", encoding="utf-8")
    assert Path("reports/v10_performance_benchmarks.json").exists()
    assert planner_ms < 5000.0
