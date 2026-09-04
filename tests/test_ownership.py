"""Tests for Effective Ownership (EO) and Strategic Risk Index engine."""

import json
from pathlib import Path
import pytest

from fpl_manager.cli import format_ownership_concise
from fpl_manager.lineup import select_starting_lineup
from fpl_manager.models import Position
from fpl_manager.ownership import (
    analyze_gameweek_ownership,
    analyze_squad_risk_profile,
    categorize_strategic_asset,
    compute_effective_ownership,
    compute_player_strategic_metrics,
    estimate_captaincy_shares,
    get_player_ownership_map,
)
from fpl_manager.storage import SnapshotStore, utc_timestamp


def test_compute_effective_ownership() -> None:
    assert compute_effective_ownership(71.5, 48.5) == 120.0
    assert compute_effective_ownership(12.0, 0.0) == 12.0


def test_categorize_strategic_asset() -> None:
    # High EO -> SHIELD
    assert categorize_strategic_asset(effective_ownership=85.0, ownership_pct=60.0, expected_points=6.0, xp_ceiling=9.0) == "SHIELD"
    assert categorize_strategic_asset(effective_ownership=42.0, ownership_pct=30.0, expected_points=5.0, xp_ceiling=7.0) == "SHIELD"
    assert categorize_strategic_asset(effective_ownership=38.0, ownership_pct=36.0, expected_points=5.0, xp_ceiling=7.0) == "SHIELD"

    # Low EO, high xP / high ceiling -> SWORD
    assert categorize_strategic_asset(effective_ownership=8.0, ownership_pct=7.0, expected_points=5.5, xp_ceiling=8.0) == "SWORD"
    assert categorize_strategic_asset(effective_ownership=14.0, ownership_pct=9.0, expected_points=3.8, xp_ceiling=7.5) == "SWORD"

    # Low EO, low xP & low ceiling -> CORE (bench fodder/unremarkable)
    assert categorize_strategic_asset(effective_ownership=5.0, ownership_pct=5.0, expected_points=2.0, xp_ceiling=4.0) == "CORE"

    # Mid EO -> CORE
    assert categorize_strategic_asset(effective_ownership=25.0, ownership_pct=22.0, expected_points=5.0, xp_ceiling=8.0) == "CORE"


@pytest.fixture
def ownership_test_env(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    store.initialize()

    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Liverpool", "short_name": "LIV"},
            {"id": 3, "name": "Manchester City", "short_name": "MCI"},
            {"id": 4, "name": "Chelsea", "short_name": "CHE"},
            {"id": 5, "name": "Tottenham", "short_name": "TOT"},
        ],
        "elements": [],
    }

    # 18 players total: 1-15 in squad, 16-18 non-owned template stars
    for p_id in range(1, 19):
        pos_id = 1 if p_id <= 2 else (2 if p_id <= 7 else (3 if p_id <= 12 else 4))
        own_pct = 70.0 if p_id in (13, 16) else (40.0 if p_id in (8, 17) else 5.0)
        pts = 40 if p_id in (13, 16) else (35 if p_id == 14 else 20)
        cost = 120 if p_id in (13, 16) else (90 if p_id == 14 else 50)
        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": ((p_id - 1) % 5) + 1,
            "element_type": pos_id,
            "now_cost": cost,
            "status": "a",
            "total_points": pts,
            "selected_by_percent": str(own_pct),
        })

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 3, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 2, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 4, "event": 2, "team_h": 5, "team_a": 1, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-08-27T17:30:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "free_transfers": 1,
        "bank_tenths": 15,
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(i): 50 for i in range(1, 16)},
    }
    squad_path.write_text(json.dumps(squad_data, indent=2), encoding="utf-8")

    return db_path, squad_path


def test_get_ownership_map_and_captaincy(ownership_test_env: tuple[Path, Path]) -> None:
    db_path, _ = ownership_test_env
    own_map = get_player_ownership_map(db_path)
    assert own_map[13] == 70.0
    assert own_map[1] == 5.0

    from fpl_manager.expected_points import project_gameweek
    projs = project_gameweek(gameweek=2, database_path=db_path)
    cap_shares = estimate_captaincy_shares(projs, own_map)

    # Top owned premium should dominate captaincy share
    assert cap_shares[13] > 0
    assert sum(cap_shares.values()) == pytest.approx(100.0, abs=1.0)


def test_analyze_gameweek_ownership(ownership_test_env: tuple[Path, Path]) -> None:
    db_path, _ = ownership_test_env
    res = analyze_gameweek_ownership(gameweek=2, database_path=db_path, top_n=5)

    assert res["gameweek"] == 2
    assert len(res["top_effective_ownership"]) <= 5
    assert any(p["strategic_category"] == "SHIELD" for p in res["top_shields"])
    assert any(p["strategic_category"] == "SWORD" for p in res["top_swords"])


def test_analyze_squad_risk_profile(ownership_test_env: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, squad_path = ownership_test_env
    rep_path = tmp_path / "ownership_report.json"

    res = analyze_squad_risk_profile(squad_path=squad_path, gameweek=2, database_path=db_path, report_path=rep_path)

    assert res["gameweek"] == 2
    assert "template_alignment_score" in res
    assert "strategic_verdict" in res
    assert len(res["starters"]) == 11
    assert len(res["bench"]) == 4

    # Captain should have 200% personal weight
    cap = next(p for p in res["starters"] if p["lineup_role"] == "CAPTAIN")
    assert cap["personal_weight_pct"] == 200.0
    assert cap["net_exposure_pct"] > 0

    # Non-owned threat 16 should be detected
    threat_ids = [t["player_id"] for t in res["top_non_owned_rank_threats"]]
    assert 16 in threat_ids
    assert rep_path.exists()


def test_lineup_serialization_with_ownership(ownership_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = ownership_test_env
    lineup_res = select_starting_lineup(squad_path=squad_path, database_path=db_path, gameweek=2)

    starters = lineup_res["starters"]
    assert "effective_ownership_pct" in starters[0]
    assert "strategic_category" in starters[0]
    assert starters[0]["strategic_category"] in ("SHIELD", "SWORD", "CORE")


def test_format_ownership_concise(ownership_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = ownership_test_env
    squad_res = analyze_squad_risk_profile(squad_path=squad_path, gameweek=2, database_path=db_path)
    concise_squad = format_ownership_concise(squad_res)
    assert "Squad Strategic Risk Profile" in concise_squad
    assert "Template Alignment:" in concise_squad
    assert "Net Exposure:" in concise_squad

    league_res = analyze_gameweek_ownership(gameweek=2, database_path=db_path)
    concise_league = format_ownership_concise(league_res)
    assert "League Effective Ownership" in concise_league
    assert "Top Template Shields" in concise_league
    assert "Top Differential Swords" in concise_league
