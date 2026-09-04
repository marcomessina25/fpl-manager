"""Tests for multi-team management and team-scoped decision persistence."""

import json
from pathlib import Path
import pytest

from fpl_manager.cli import main
from fpl_manager.decision_log import (
    get_gameweek_decision,
    list_decisions,
    record_actual_gameweek_score,
    record_gameweek_decision,
)
from fpl_manager.evaluation import evaluate_gameweek_decision
from fpl_manager.squad_state import CurrentSquadState, load_current_squad, save_current_squad
from fpl_manager.storage import SnapshotStore, utc_timestamp
from fpl_manager.teams import (
    create_team,
    delete_team,
    ensure_teams_initialized,
    get_active_squad_path,
    get_active_team_id,
    get_team,
    get_team_id_from_squad_path,
    get_team_squad_path,
    list_teams,
    set_active_team,
    slugify_team_id,
)


@pytest.fixture
def teams_test_env(tmp_path: Path) -> tuple[Path, Path]:
    """Sets up a mock environment with database and config directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "fpl.sqlite3"

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

    for p_id in range(1, 18):
        pos_id = 1 if p_id <= 2 else (2 if p_id <= 7 else (3 if p_id <= 12 else 4))
        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": 5 if p_id == 16 else (((p_id - 1) % 5) + 1),
            "element_type": pos_id,
            "now_cost": 50,
            "status": "a",
            "total_points": 30,
        })

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-20T15:00:00Z", "finished": True},
        {"id": 2, "event": 2, "team_h": 2, "team_a": 3, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-27T15:00:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    # Create a base legacy current_squad.json
    base_squad = CurrentSquadState(
        player_ids=tuple(range(1, 16)),
        purchase_prices_tenths={p: 50 for p in range(1, 16)},
        bank_tenths=20,
        free_transfers=1,
        chips_remaining=("wildcard", "freehit", "benchboost", "triplecaptain"),
        season="2026/27",
        gameweek=2,
    )
    save_current_squad(config_dir / "current_squad.json", base_squad)

    return config_dir, db_path


def test_slugify_team_id() -> None:
    assert slugify_team_id("My Dream Team") == "my-dream-team"
    assert slugify_team_id("  Arsenal XI #1  ") == "arsenal-xi-1"
    assert slugify_team_id("$$$") == "team"
    assert slugify_team_id("") == "team"


def test_ensure_teams_initialized_and_list(teams_test_env: tuple[Path, Path]) -> None:
    config_dir, _ = teams_test_env

    ensure_teams_initialized(config_dir)

    default_team_dir = config_dir / "teams" / "default"
    assert default_team_dir.exists()
    assert (default_team_dir / "squad.json").exists()
    assert (default_team_dir / "metadata.json").exists()
    assert (config_dir / "active_team.json").exists()

    teams = list_teams(config_dir)
    assert len(teams) == 1
    assert teams[0]["team_id"] == "default"
    assert teams[0]["is_active"] is True
    assert teams[0]["gameweek"] == 2
    assert teams[0]["bank_millions"] == 2.0


def test_create_and_switch_teams(teams_test_env: tuple[Path, Path]) -> None:
    config_dir, _ = teams_test_env

    # Create new team
    new_team = create_team(
        name="Differential Kings",
        team_id="diff-kings",
        manager="Marco",
        config_dir=config_dir,
        set_as_active=True,
    )

    assert new_team["team_id"] == "diff-kings"
    assert new_team["is_active"] is True
    assert get_active_team_id(config_dir) == "diff-kings"

    teams = list_teams(config_dir)
    assert len(teams) == 2
    active = [t for t in teams if t["is_active"]]
    assert len(active) == 1
    assert active[0]["team_id"] == "diff-kings"

    # Switch back to default
    switched = set_active_team("default", config_dir)
    assert switched["team_id"] == "default"
    assert get_active_team_id(config_dir) == "default"

    # Verify invalid switch raises
    with pytest.raises(ValueError, match="does not exist"):
        set_active_team("non-existent-team", config_dir)


def test_create_team_validations_and_copy(teams_test_env: tuple[Path, Path]) -> None:
    config_dir, _ = teams_test_env

    # Empty name
    with pytest.raises(ValueError, match="Team name cannot be empty"):
        create_team("", config_dir=config_dir)

    # First team created
    create_team("Team Alpha", team_id="alpha", manager="Alice", config_dir=config_dir, set_as_active=False)

    # Duplicate team ID
    with pytest.raises(ValueError, match="already exists"):
        create_team("Team Alpha", team_id="alpha", config_dir=config_dir)

    # Copy from existing team
    beta = create_team("Team Beta", team_id="beta", copy_from_team_id="alpha", config_dir=config_dir)
    assert beta["team_id"] == "beta"
    beta_squad = load_current_squad(Path(beta["squad_path"]))
    assert beta_squad.gameweek == 2
    assert beta_squad.player_ids == tuple(range(1, 16))

    # Copy from invalid team
    with pytest.raises(ValueError, match="Team to copy from 'nonexistent' not found"):
        create_team("Team Gamma", copy_from_team_id="nonexistent", config_dir=config_dir)


def test_delete_team(teams_test_env: tuple[Path, Path]) -> None:
    config_dir, _ = teams_test_env

    # Cannot delete default team
    with pytest.raises(ValueError, match="Cannot delete the default team"):
        delete_team("default", config_dir=config_dir)

    # Create team to delete
    create_team("Disposable Team", team_id="disposable", config_dir=config_dir, set_as_active=True)
    assert get_active_team_id(config_dir) == "disposable"

    # Delete team while active: should reset active to default
    res = delete_team("disposable", config_dir=config_dir)
    assert res["deleted_team_id"] == "disposable"
    assert res["active_team_id"] == "default"
    assert get_active_team_id(config_dir) == "default"

    # Attempt to delete non-existent team
    with pytest.raises(ValueError, match="not found"):
        delete_team("disposable", config_dir=config_dir)


def test_get_team_info(teams_test_env: tuple[Path, Path]) -> None:
    config_dir, _ = teams_test_env

    info = get_team("default", config_dir=config_dir)
    assert info["metadata"]["team_id"] == "default"
    assert isinstance(info["state"], CurrentSquadState)
    assert info["is_active"] is True


def test_get_squad_paths(teams_test_env: tuple[Path, Path]) -> None:
    config_dir, _ = teams_test_env

    default_path = get_team_squad_path("default", config_dir=config_dir)
    assert default_path.exists()
    assert get_team_id_from_squad_path(default_path, config_dir=config_dir) == "default"

    create_team("Alt Team", team_id="alt-team", config_dir=config_dir, set_as_active=False)
    alt_path = get_team_squad_path("alt-team", config_dir=config_dir)
    assert alt_path.exists()
    assert get_team_id_from_squad_path(alt_path, config_dir=config_dir) == "alt-team"


def test_multi_team_decisions_isolation(teams_test_env: tuple[Path, Path]) -> None:
    config_dir, db_path = teams_test_env

    squad_ids = list(range(1, 16))
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    bench = [2, 6, 7, 15]

    # Team 1 decision (Captain 13)
    dec1 = record_gameweek_decision(
        gameweek=2,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        team_id="team-alpha",
        season="2026/27",
        database_path=db_path,
    )
    assert dec1["captain_id"] == 13
    assert dec1["team_id"] == "team-alpha"

    # Team 2 decision in SAME season and gameweek (Captain 8)
    dec2 = record_gameweek_decision(
        gameweek=2,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=8,
        vice_captain_id=13,
        team_id="team-beta",
        season="2026/27",
        database_path=db_path,
    )
    assert dec2["captain_id"] == 8
    assert dec2["team_id"] == "team-beta"

    # Verify querying by team_id yields correct separate decisions
    q1 = get_gameweek_decision(2, team_id="team-alpha", database_path=db_path)
    assert q1 is not None
    assert q1["captain_id"] == 13
    assert q1["team_id"] == "team-alpha"

    q2 = get_gameweek_decision(2, team_id="team-beta", database_path=db_path)
    assert q2 is not None
    assert q2["captain_id"] == 8
    assert q2["team_id"] == "team-beta"

    # Verify list_decisions respects team_id
    list1 = list_decisions(team_id="team-alpha", database_path=db_path)
    assert len(list1) == 1
    assert list1[0]["captain_id"] == 13

    list2 = list_decisions(team_id="team-beta", database_path=db_path)
    assert len(list2) == 1
    assert list2[0]["captain_id"] == 8


def test_multi_team_evaluations_isolation(teams_test_env: tuple[Path, Path]) -> None:
    config_dir, db_path = teams_test_env

    squad_ids = list(range(1, 16))
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
    bench = [2, 6, 7, 15]

    # Record decisions
    record_gameweek_decision(
        gameweek=2,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=13,
        vice_captain_id=8,
        team_id="alpha",
        season="2026/27",
        database_path=db_path,
    )
    record_gameweek_decision(
        gameweek=2,
        squad_player_ids=squad_ids,
        starting_player_ids=starters,
        bench_player_ids=bench,
        captain_id=8,
        vice_captain_id=13,
        team_id="beta",
        season="2026/27",
        database_path=db_path,
    )

    # Actual scores: player 13 scored 10 pts, player 8 scored 2 pts
    scores = {p: 2.0 for p in range(1, 16)}
    scores[13] = 10.0

    eval_alpha = evaluate_gameweek_decision(
        gameweek=2,
        team_id="alpha",
        actual_scores=scores,
        database_path=db_path,
    )
    assert eval_alpha["team_id"] == "alpha"
    assert eval_alpha["captaincy"]["captain_id"] == 13
    assert eval_alpha["captaincy"]["captain_actual_points"] == 10.0

    eval_beta = evaluate_gameweek_decision(
        gameweek=2,
        team_id="beta",
        actual_scores=scores,
        database_path=db_path,
    )
    assert eval_beta["team_id"] == "beta"
    assert eval_beta["captaincy"]["captain_id"] == 8
    assert eval_beta["captaincy"]["captain_actual_points"] == 2.0


def test_cli_teams_flow(teams_test_env: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    config_dir, db_path = teams_test_env

    import fpl_manager.cli as cli_mod
    import fpl_manager.teams as teams_mod

    monkeypatch.setattr(cli_mod, "DATABASE_PATH", db_path)
    monkeypatch.setattr(teams_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(teams_mod, "TEAMS_DIR", config_dir / "teams")
    monkeypatch.setattr(teams_mod, "DEFAULT_SQUAD_PATH", config_dir / "current_squad.json")
    monkeypatch.setattr(teams_mod, "ACTIVE_TEAM_PATH", config_dir / "active_team.json")

    # 1. fpl teams
    main(["teams"])
    out, _ = capsys.readouterr()
    assert "default" in out
    assert "Default Team" in out

    # 2. fpl team create "League Winner" --manager "Pep" --activate
    main(["team", "create", "League Winner", "--manager", "Pep", "--activate"])
    out, _ = capsys.readouterr()
    assert "Created team 'League Winner' [league-winner] and set as active." in out

    # 3. fpl team info
    main(["team", "info"])
    out, _ = capsys.readouterr()
    assert "League Winner [league-winner] (Active Team)" in out
    assert "Manager: Pep" in out

    # 4. fpl team switch default
    main(["team", "switch", "default"])
    out, _ = capsys.readouterr()
    assert "Switched active team to 'Default Team' [default]." in out

    # 5. fpl team delete league-winner
    main(["team", "delete", "league-winner"])
    out, _ = capsys.readouterr()
    assert "Deleted team 'league-winner'. Active team is now 'default'." in out
