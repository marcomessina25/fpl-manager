"""Tests for automated transfer suggestion module."""

import json
from pathlib import Path
import pytest

from fpl_manager.storage import SnapshotStore, utc_timestamp
from fpl_manager.suggest_transfers import suggest_transfers


@pytest.fixture
def mock_suggest_db(tmp_path: Path) -> tuple[Path, Path]:
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

    # 15 players in squad (IDs 1..15)
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
        })

    # Add candidate GKP (id 101), DEF (id 102), MID (id 103), FWD (id 104)
    bootstrap["elements"].extend([
        {"id": 101, "web_name": "Target_GKP", "team": 1, "element_type": 1, "now_cost": 50, "status": "a", "total_points": 80},
        {"id": 102, "web_name": "Target_DEF", "team": 2, "element_type": 2, "now_cost": 50, "status": "a", "total_points": 90},
        {"id": 103, "web_name": "Target_MID", "team": 3, "element_type": 3, "now_cost": 50, "status": "a", "total_points": 100},
        {"id": 104, "web_name": "Target_FWD", "team": 1, "element_type": 4, "now_cost": 50, "status": "a", "total_points": 70},
    ])

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 2, "team_a": 3, "team_h_difficulty": 2, "team_a_difficulty": 2, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "player_ids": player_ids,
        "purchase_prices_tenths": {str(pid): 50 for pid in player_ids},
        "bank_tenths": 10,
        "free_transfers": 1,
        "chips_remaining": [],
    }
    squad_path.write_text(json.dumps(squad_data), encoding="utf-8")

    return db_path, squad_path


def test_suggest_transfers_1_move(tmp_path: Path, mock_suggest_db: tuple[Path, Path]) -> None:
    db_path, squad_path = mock_suggest_db
    report_file = tmp_path / "transfer_suggestions.json"

    res = suggest_transfers(
        num_transfers=1,
        squad_path=squad_path,
        database_path=db_path,
        max_results=5,
        num_gameweeks=1,
        report_path=report_file,
    )

    assert res["num_transfers"] == 1
    assert len(res["top_suggestions"]) > 0
    top = res["top_suggestions"][0]
    assert top["type"] == "1-transfer"
    assert len(top["outgoing"]) == 1
    assert len(top["incoming"]) == 1
    assert report_file.is_file()


def test_suggest_transfers_2_moves(tmp_path: Path, mock_suggest_db: tuple[Path, Path]) -> None:
    db_path, squad_path = mock_suggest_db
    report_file = tmp_path / "transfer_suggestions.json"

    res = suggest_transfers(
        num_transfers=2,
        squad_path=squad_path,
        database_path=db_path,
        max_results=5,
        num_gameweeks=1,
        report_path=report_file,
    )

    assert res["num_transfers"] == 2
    assert len(res["top_suggestions"]) > 0
    top = res["top_suggestions"][0]
    assert top["type"] == "2-transfer"
    assert len(top["outgoing"]) == 2
    assert len(top["incoming"]) == 2


def test_suggest_transfers_3_moves(tmp_path: Path, mock_suggest_db: tuple[Path, Path]) -> None:
    db_path, squad_path = mock_suggest_db
    report_file = tmp_path / "transfer_suggestions.json"

    res = suggest_transfers(
        num_transfers=3,
        squad_path=squad_path,
        database_path=db_path,
        max_results=5,
        num_gameweeks=1,
        report_path=report_file,
    )

    assert res["num_transfers"] == 3
    assert len(res["top_suggestions"]) > 0
    top = res["top_suggestions"][0]
    assert top["type"] == "3-transfer"
    assert len(top["outgoing"]) == 3
    assert len(top["incoming"]) == 3


def test_suggest_transfers_4_moves(tmp_path: Path, mock_suggest_db: tuple[Path, Path]) -> None:
    db_path, squad_path = mock_suggest_db
    report_file = tmp_path / "transfer_suggestions.json"

    res = suggest_transfers(
        num_transfers=4,
        squad_path=squad_path,
        database_path=db_path,
        max_results=5,
        num_gameweeks=1,
        report_path=report_file,
    )

    assert res["num_transfers"] == 4
    assert len(res["top_suggestions"]) > 0
    top = res["top_suggestions"][0]
    assert top["type"] == "4-transfer"
    assert len(top["outgoing"]) == 4
    assert len(top["incoming"]) == 4


def test_suggest_transfers_limit(tmp_path: Path, mock_suggest_db: tuple[Path, Path]) -> None:
    db_path, squad_path = mock_suggest_db
    report_file = tmp_path / "transfer_suggestions.json"

    with pytest.raises(ValueError, match="supports between 1 and 5 transfers"):
        suggest_transfers(
            num_transfers=6,
            squad_path=squad_path,
            database_path=db_path,
            max_results=5,
            num_gameweeks=1,
            report_path=report_file,
        )


def test_suggest_transfers_with_risk_profiles(tmp_path: Path, mock_suggest_db: tuple[Path, Path]) -> None:
    db_path, squad_path = mock_suggest_db
    report_file = tmp_path / "transfer_suggestions.json"

    for risk in ("neutral", "floor", "ceiling", "chase", "defend_lead"):
        res = suggest_transfers(
            num_transfers=1,
            squad_path=squad_path,
            database_path=db_path,
            max_results=5,
            num_gameweeks=1,
            risk_profile=risk,
            report_path=report_file,
        )
        assert res["risk_profile"] == risk
        assert len(res["top_suggestions"]) > 0
        top = res["top_suggestions"][0]
        assert "floor_delta" in top
        assert "ceiling_delta" in top
        assert "xp_delta" in top
        assert top["risk_profile"] == risk
        assert top["score"] == top["profile_net_gain"]

    with pytest.raises(ValueError, match="Invalid risk_profile"):
        suggest_transfers(
            num_transfers=1,
            squad_path=squad_path,
            database_path=db_path,
            risk_profile="invalid_profile",
            report_path=report_file,
        )


@pytest.mark.parametrize("budget_millions", [None, 77.5])
def test_strategic_service_preserves_retained_prices_and_constraints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, budget_millions: float | None
) -> None:
    import importlib
    from fpl_manager.models import Position
    from fpl_manager.strategic_squad import StrategicConstraints
    from fpl_manager.suggest_transfers import PlayerInfo

    service = importlib.import_module("fpl_manager.suggest_transfers")
    players = {
        pid: PlayerInfo(
            pid, f"Player {pid}",
            Position(1 if pid <= 2 else 2 if pid <= 7 else 3 if pid <= 12 else 4),
            pid, f"T{pid}", 50, "a", 0, expected_points=4.0,
            xp_floor=3.0, xp_ceiling=5.0, gw_breakdown_xp={2: 4.0},
        )
        for pid in range(1, 16)
    }
    constraints = StrategicConstraints(
        budget_tenths=775, locked_player_ids=set(players), bench_weight=0.15,
        effective_prices_tenths={pid: 45 for pid in players},
        min_bank_tenths=10, preferred_player_ids={13}, soft_preference_weight=2.0,
    )
    monkeypatch.setattr(service, "get_current_gameweek", lambda store: 2)
    monkeypatch.setattr(service, "project_multi_gameweek_profiles", lambda *args, **kwargs: {})
    monkeypatch.setattr(service, "load_all_players_meta", lambda *args: (players, {}))
    actual_solve = service.solve_strategic_squad
    received_constraints = []

    def solve_with_actual_optimizer(**kwargs):
        received_constraints.append(kwargs["constraints"])
        return actual_solve(**kwargs)

    monkeypatch.setattr(service, "solve_strategic_squad", solve_with_actual_optimizer)
    result = service.suggest_strategic_squad(
        mode="wildcard", budget_millions=budget_millions, constraints=constraints,
        database_path=tmp_path / "unused.sqlite3", num_gameweeks=1,
        generate_all_candidates=False, report_path=tmp_path / "strategic.json",
    )

    assert result["total_cost_tenths"] == 675
    assert result["bank_remaining_tenths"] == 100
    effective = received_constraints[0]
    assert effective.effective_prices_tenths == constraints.effective_prices_tenths
    assert effective.bench_weight == 0.15
    assert effective.min_bank_tenths == 10
    assert effective.soft_preference_weight == 2.0
    assert effective.preferred_player_ids == {13}
    assert constraints.target_gameweeks == ()
