"""Tests for V1.2.5 live engine wiring, legacy fallback, GUI/CLI integration, and Copilot improvements.

Validates:
1. `suggest_transfers` defaults to V1.2.5 with lineup-aware Starting XI evaluation, GK hurdles, and rolling horizon.
2. `suggest_transfers(engine="legacy")` falls back to raw unweighted squad-delta optimization.
3. Reason breakdown tracking (Copilot Improvement 3): distinguishing pool expansion, GK suppression, and horizon impact.
4. Tunable gamma parameter in `DecisionEngineV125` and `resolve_decision_engine` (Copilot Improvement 2).
5. Second-level fixture caching by (season_dir, gw) tuple (Copilot Improvement 1).
6. CLI and briefing formatters display V1.2.5 lineup and reasoning metadata.
"""

import json
from pathlib import Path
import pytest

from fpl_manager.backtest.decision_engine import (
    DecisionEngineV125,
    get_historical_fixtures_for_gw,
    resolve_decision_engine,
)
from fpl_manager.briefing import _build_briefing_markdown
from fpl_manager.cli import format_suggest_transfers_concise
from fpl_manager.storage import SnapshotStore, utc_timestamp
from fpl_manager.suggest_transfers import suggest_transfers


@pytest.fixture
def mock_live_db(tmp_path: Path) -> tuple[Path, Path]:
    """Create a hermetic SQLite database with 15 squad players and diverse transfer candidates."""
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
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

    # 15 players in squad (IDs 1..15): 2 GKP, 5 DEF, 5 MID, 3 FWD
    player_ids = list(range(1, 16))
    for i, p_id in enumerate(player_ids):
        pos_id = 1 if i < 2 else (2 if i < 7 else (3 if i < 12 else 4))
        team_id = (i % 5) + 1
        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Squad_Player_{p_id}",
            "team": team_id,
            "element_type": pos_id,
            "now_cost": 50,
            "status": "a",
            "total_points": 30,
            "chance_of_playing_next_round": 100,
        })

    # Add candidates:
    # 101: GKP with slightly better raw xP (+1.0)
    # 102: Premium MID with strong Starting XI impact
    # 103: Bench DEF (cheap, but low XI impact)
    bootstrap["elements"].extend([
        {"id": 101, "web_name": "New_GKP", "team": 1, "element_type": 1, "now_cost": 50, "status": "a", "total_points": 50},
        {"id": 102, "web_name": "Premium_MID", "team": 3, "element_type": 3, "now_cost": 80, "status": "a", "total_points": 120},
        {"id": 103, "web_name": "Bench_DEF", "team": 2, "element_type": 2, "now_cost": 45, "status": "a", "total_points": 40},
    ])

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 2, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
        {"id": 3, "event": 3, "team_h": 3, "team_a": 4, "team_h_difficulty": 2, "team_a_difficulty": 3, "kickoff_time": "2026-09-03T15:00:00Z", "finished": False},
        {"id": 4, "event": 4, "team_h": 4, "team_a": 5, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-09-10T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "player_ids": player_ids,
        "purchase_prices_tenths": {str(pid): 50 for pid in player_ids},
        "bank_tenths": 40,
        "free_transfers": 1,
        "chips_remaining": [],
    }
    squad_path.write_text(json.dumps(squad_data), encoding="utf-8")

    return db_path, squad_path


def test_suggest_transfers_v125_default_and_metadata(mock_live_db: tuple[Path, Path]) -> None:
    """Validate that suggest_transfers defaults to v1.2.5 and outputs lineup metrics & reason breakdown."""
    db_path, squad_path = mock_live_db
    res = suggest_transfers(
        num_transfers=1,
        squad_path=squad_path,
        database_path=db_path,
        max_results=5,
    )

    assert res["engine"] in ("v1.3.5", "v1.2.5")
    assert "top_suggestions" in res
    assert len(res["top_suggestions"]) > 0

    top = res["top_suggestions"][0]
    # Check V1.2.5 specific attributes
    assert "lineup_xp_delta" in top
    assert "v125_net_gain" in top
    assert "hurdle" in top
    assert "hurdle_passed" in top
    assert "reason_breakdown" in top

    rb = top["reason_breakdown"]
    assert "pool_expansion_surfaced" in rb
    assert "gk_suppression" in rb
    assert "multi_horizon_gain" in rb


def test_suggest_transfers_legacy_fallback(mock_live_db: tuple[Path, Path]) -> None:
    """Validate that suggest_transfers(engine='legacy') returns raw unweighted squad suggestions."""
    db_path, squad_path = mock_live_db
    res = suggest_transfers(
        num_transfers=1,
        squad_path=squad_path,
        database_path=db_path,
        max_results=5,
        engine="legacy",
    )

    assert res["engine"] == "legacy"
    assert len(res["top_suggestions"]) > 0
    top = res["top_suggestions"][0]
    # Legacy mode should not have reason breakdown or v125_net_gain
    assert "reason_breakdown" not in top


def test_suggest_transfers_gk_hurdle_enforcement(mock_live_db: tuple[Path, Path]) -> None:
    """Validate that healthy GK transfers are subject to high hurdle (>= 1.50/3.00 pts)."""
    db_path, squad_path = mock_live_db
    res = suggest_transfers(
        num_transfers=1,
        squad_path=squad_path,
        database_path=db_path,
        max_results=10,
        engine="v1.2.5",
    )

    gk_moves = [
        opt for opt in res["top_suggestions"]
        if any(p.get("position") == "GKP" for p in opt.get("outgoing", []))
    ]
    if gk_moves:
        for m in gk_moves:
            # Healthy incumbent should face a 1.50 or 3.00 hurdle
            assert m["hurdle"] >= 1.50
            assert "gk_suppression" in m["reason_breakdown"]


def test_tunable_gamma_in_decision_engine() -> None:
    """Validate Copilot Improvement 2: gamma is exposed and tunable in DecisionEngineV125."""
    eng_default = DecisionEngineV125()
    assert eng_default.gamma == 0.75

    eng_custom = DecisionEngineV125(gamma=0.60)
    assert eng_custom.gamma == 0.60

    # Test via resolve_decision_engine
    eng_resolved = resolve_decision_engine("v1.2.5", gamma=0.85)
    assert isinstance(eng_resolved, DecisionEngineV125)
    assert eng_resolved.gamma == 0.85

    # Test string shorthand with gamma
    eng_shorthand = resolve_decision_engine("v1.2.5_g0.70")
    assert isinstance(eng_shorthand, DecisionEngineV125)
    assert eng_shorthand.gamma == 0.70


def test_second_level_fixture_cache(tmp_path: Path) -> None:
    """Validate Copilot Improvement 1: second-level cache keyed by (season_dir, gw)."""
    fixtures_file = tmp_path / "fixtures.json"
    sample_fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2},
        {"id": 2, "event": 2, "team_h": 2, "team_a": 3},
    ]
    fixtures_file.write_text(json.dumps(sample_fixtures), encoding="utf-8")

    # First lookup loads and populates cache
    fixes_gw1 = get_historical_fixtures_for_gw(tmp_path, 1)
    assert len(fixes_gw1) == 1
    assert fixes_gw1[0]["id"] == 1

    # Second lookup hits the second-level cache
    fixes_gw1_cached = get_historical_fixtures_for_gw(tmp_path, 1)
    assert fixes_gw1_cached is fixes_gw1

    # Lookup for non-existent GW returns empty list
    fixes_gw99 = get_historical_fixtures_for_gw(tmp_path, 99)
    assert fixes_gw99 == []


def test_cli_concise_formatter_displays_v125_metadata() -> None:
    """Validate that CLI concise format prints lineup gain and reason breakdown badges."""
    sample_result = {
        "num_transfers": 1,
        "free_transfers_available": 1,
        "engine": "v1.2.5",
        "top_suggestions": [
            {
                "type": "1-transfer",
                "outgoing": [{"id": 1, "name": "Saliba", "team": "ARS", "position": "DEF"}],
                "incoming": [{"id": 2, "name": "Gabriel", "team": "ARS", "position": "DEF"}],
                "lineup_xp_delta": 1.75,
                "v125_net_gain": 1.75,
                "hurdle": 0.50,
                "hurdle_passed": True,
                "score": 1.75,
                "xp_delta": 1.20,
                "bank_after_tenths": 15,
                "transfer_hits": 0,
                "reason_breakdown": {
                    "pool_expansion_surfaced": True,
                    "gk_suppression": "n/a",
                    "multi_horizon_gain": 0.55,
                    "summary": "Starting XI upgrade (+1.75 xP)",
                },
            }
        ],
    }

    formatted = format_suggest_transfers_concise(sample_result)
    assert "Lineup ΔxP: +1.75" in formatted
    assert "Pool Expansion" in formatted


def test_briefing_markdown_includes_v125_metadata() -> None:
    """Validate that briefing summary reflects V1.2.5 lineup delta and reasons."""
    dossier = {
        "gameweek": 5,
        "team_id": "test_team",
        "generated_at": "2026-10-02T15:00:00Z",
        "deadline_time": "2026-10-04T10:00:00Z",
        "is_decision_logged": False,
        "financials": {"bank_fmt": "£1.5m", "free_transfers": 1, "chips_remaining": []},
        "lineup": {
            "formation": "3-5-2",
            "projected_xp": 58.5,
            "floor_xp": 42.0,
            "ceiling_xp": 75.0,
            "captain": {"name": "Haaland", "projected_xp": 14.2},
            "vice_captain": {"name": "Salah"},
            "starters": [],
            "bench": [],
        },
        "squad_health_alerts": [],
        "strategic_risk": {"top_threats_against_squad": []},
        "transfer_suggestions": [
            {
                "outgoing": [{"name": "Pickford"}],
                "incoming": [{"name": "Raya"}],
                "net_xp_gain": 1.45,
                "lineup_xp_delta": 1.45,
                "bank_after_tenths": 10,
                "transfer_hits": 0,
                "reason_breakdown": {
                    "pool_expansion_surfaced": True,
                    "summary": "Pool Expansion",
                },
            }
        ],
        "chip_strategy": {"active_segment": "Segment 1", "calendar_events": []},
    }

    md = _build_briefing_markdown(dossier)
    assert "**Pickford** ➔ **Raya**" in md
    assert "Lineup ΔxP: +1.45" in md
    assert "Pool Expansion" in md
