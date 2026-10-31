"""Tests for multi-team management and team-scoped decision persistence."""

import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import subprocess
import sys
import time
from dataclasses import replace
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
    rename_team,
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


def test_auto_created_team_id_is_pinned_under_interleaving(teams_test_env, monkeypatch):
    from fpl_manager.application import CommandBus, LiveContext
    config, database = teams_test_env
    ensure_teams_initialized(config)
    execute = CommandBus.execute
    barrier = Barrier(2)

    def interleave(self, context, operation, payload, action, *args, **kwargs):
        if operation == "create_team" and context.team_id == "same-name":
            barrier.wait(timeout=10)
        return execute(self, context, operation, payload, action, *args, **kwargs)

    monkeypatch.setattr(CommandBus, "execute", interleave)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(create_team, "Same Name", config_dir=config,
                               database_path=database, set_as_active=False) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert {result["team_id"] for result in results} == {"same-name", "same-name-2"}
    for result in results:
        assert Path(result["squad_path"]).parent.name == result["team_id"]
        assert CommandBus(database).revision(LiveContext(result["team_id"], "2026/27", 2)) == 1
    with SnapshotStore(database)._connect() as connection:
        rows = connection.execute(
            "SELECT context_json, receipt_json FROM application_commands WHERE operation='create_team'"
        ).fetchall()
    assert len(rows) == 2
    for context, receipt in rows:
        assert json.loads(context)["team_id"] == json.loads(receipt)["result"]["team_id"]


def test_auto_creation_ids_and_revisions_are_cross_process_safe(teams_test_env):
    from fpl_manager.application import CommandBus, LiveContext
    config, database = teams_test_env
    ensure_teams_initialized(config)
    gate = config / "create-gate"
    gate.mkdir()
    script = (
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "from fpl_manager.teams import create_team\n"
        "gate = Path(sys.argv[3])\n"
        "(gate / (str(os.getpid()) + '.ready')).touch()\n"
        "deadline = time.monotonic() + 30\n"
        "while not (gate / 'go').exists():\n"
        "    if time.monotonic() >= deadline: raise TimeoutError('start gate')\n"
        "    time.sleep(0.02)\n"
        "result = create_team('Process Team', config_dir=Path(sys.argv[1]), "
        "database_path=Path(sys.argv[2]), set_as_active=False)\n"
        "print(json.dumps(result))\n"
    )
    processes = [subprocess.Popen(
        [sys.executable, "-c", script, str(config), str(database), str(gate)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) for _ in range(3)]
    try:
        deadline = time.monotonic() + 30
        while len(list(gate.glob("*.ready"))) != 3:
            assert time.monotonic() < deadline, "Subprocess startup timed out"
            time.sleep(0.02)
        (gate / "go").touch()
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)
    assert {result["team_id"] for result in results} == {
        "process-team", "process-team-2", "process-team-3",
    }
    for result in results:
        tid = result["team_id"]
        assert Path(result["squad_path"]).parent.name == tid
        assert CommandBus(database).revision(LiveContext(tid, "2026/27", 2)) == 1


def test_explicit_concurrent_duplicate_is_not_auto_renamed(teams_test_env):
    from fpl_manager.application import CommandBus, LiveContext
    config, database = teams_test_env
    ensure_teams_initialized(config)
    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=10)
        try:
            return create_team("Explicit", team_id="exact", config_dir=config,
                               database_path=database, set_as_active=False)
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=30) for future in [pool.submit(create), pool.submit(create)]]
    successes = [result for result in results if isinstance(result, dict)]
    errors = [result for result in results if isinstance(result, ValueError)]
    assert len(successes) == len(errors) == 1
    assert successes[0]["team_id"] == "exact" and "already exists" in str(errors[0])
    assert CommandBus(database).revision(LiveContext("exact", "2026/27", 2)) == 1
    assert not (config / "teams" / "exact-2").exists()


@pytest.mark.parametrize("activate", [False, True])
@pytest.mark.parametrize("collide", [False, True])
def test_create_pins_source_season_and_bank_before_active_team_switch(teams_test_env, monkeypatch, activate, collide):
    from fpl_manager.application import CommandBus, LiveContext
    config, database = teams_test_env
    alpha = load_current_squad(config / "current_squad.json")
    beta = replace(alpha, season="2025/26", bank_tenths=77, gameweek=4)
    create_team("Alpha", team_id="alpha", squad_state=alpha, config_dir=config, database_path=database)
    create_team("Beta", team_id="beta", squad_state=beta, config_dir=config,
                database_path=database, set_as_active=False)
    execute = CommandBus.execute
    switched = False

    def switch_source(self, context, operation, payload, action, *args, **kwargs):
        nonlocal switched
        if operation == "create_team" and context.team_id == "copied" and not switched:
            switched = True
            if collide:
                create_team("Occupied", team_id="copied", squad_state=beta, config_dir=config,
                            database_path=database, set_as_active=False)
            set_active_team("beta", config_dir=config, database_path=database)
        return execute(self, context, operation, payload, action, *args, **kwargs)

    monkeypatch.setattr(CommandBus, "execute", switch_source)
    result = create_team("Copied", config_dir=config, database_path=database, set_as_active=activate)
    copied = load_current_squad(Path(result["squad_path"]))
    tid = "copied-2" if collide else "copied"
    assert switched and result["team_id"] == tid
    assert copied.season == alpha.season and copied.bank_tenths == alpha.bank_tenths
    assert copied.gameweek == alpha.gameweek
    assert CommandBus(database).revision(LiveContext(tid, alpha.season, alpha.gameweek)) == 1
    assert CommandBus(database).revision(LiveContext(tid, beta.season, beta.gameweek)) == 0
    assert get_active_team_id(config) == (tid if activate else "beta")
    with SnapshotStore(database)._connect() as connection:
        context_json, receipt_json = connection.execute(
            "SELECT context_json, receipt_json FROM application_commands "
            "WHERE operation='create_team' ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
    assert json.loads(context_json) == LiveContext(tid, alpha.season, alpha.gameweek).to_dict()
    assert json.loads(receipt_json)["result"]["squad_path"] == result["squad_path"]


def test_create_does_not_derive_source_from_a_racing_target(teams_test_env, monkeypatch):
    from fpl_manager import teams
    from fpl_manager.application import CommandBus, LiveContext
    config, database = teams_test_env
    source = load_current_squad(config / "current_squad.json")
    occupant = replace(source, season="2025/26", bank_tenths=88, gameweek=4)
    ensure_teams_initialized(config)
    exists = teams.team_workspace_exists
    inserted = False

    def occupy_after_lookup(team_id, config_dir=None):
        nonlocal inserted
        result = exists(team_id, config_dir)
        if team_id == "racing" and not result and not inserted:
            inserted = True
            create_team("Occupant", team_id="racing", squad_state=occupant, config_dir=config,
                        database_path=database, set_as_active=False)
        return result

    monkeypatch.setattr(teams, "team_workspace_exists", occupy_after_lookup)
    result = create_team("Racing", config_dir=config, database_path=database, set_as_active=False)
    copied = load_current_squad(Path(result["squad_path"]))
    assert result["team_id"] == "racing-2"
    assert copied.season == source.season and copied.bank_tenths == source.bank_tenths
    assert copied.gameweek == source.gameweek
    assert CommandBus(database).revision(LiveContext("racing-2", source.season, source.gameweek)) == 1
    assert CommandBus(database).revision(LiveContext("racing-2", occupant.season, occupant.gameweek)) == 0


def test_create_template_fallback_uses_its_exact_period(teams_test_env):
    from fpl_manager.application import CommandBus, LiveContext
    config, database = teams_test_env
    legacy = config / "current_squad.json"
    template = replace(load_current_squad(legacy), season="2025/26", bank_tenths=39, gameweek=4)
    legacy.unlink()
    save_current_squad(config / "current_squad.example.json", template)
    result = create_team("Template Copy", config_dir=config, database_path=database)
    copied = load_current_squad(Path(result["squad_path"]))
    assert copied.season == template.season and copied.bank_tenths == template.bank_tenths
    assert copied.gameweek == template.gameweek
    assert CommandBus(database).revision(LiveContext("template-copy", template.season, template.gameweek)) == 1


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


def test_team_commands_use_configured_database(teams_test_env: tuple[Path, Path]) -> None:
    config_dir, db_path = teams_test_env
    derived_database = config_dir.parent / "data" / "fpl.sqlite3"
    create_team("Journal Team", team_id="journal", config_dir=config_dir, set_as_active=False, database_path=db_path)
    set_active_team("journal", config_dir=config_dir, database_path=db_path)
    rename_team("journal", "Journal Renamed", config_dir=config_dir, database_path=db_path)
    delete_team("journal", config_dir=config_dir, database_path=db_path)
    assert not derived_database.exists()
    with SnapshotStore(db_path)._connect() as connection:
        operations = connection.execute(
            "SELECT operation FROM application_commands ORDER BY sequence"
        ).fetchall()
    assert [row[0] for row in operations] == [
        "create_team", "set_active_team", "rename_team", "delete_team",
    ]


@pytest.mark.parametrize("explicit_id", [False, True])
def test_deleted_team_id_can_be_recreated(teams_test_env, explicit_id):
    config_dir, db_path = teams_test_env
    arguments = {"team_id": "reusable-team"} if explicit_id else {}
    first = create_team("Reusable Team", config_dir=config_dir, database_path=db_path, **arguments)
    delete_team(first["team_id"], config_dir=config_dir, database_path=db_path)
    assert (config_dir / "teams" / "reusable-team").is_dir()
    recreated = create_team("Reusable Team", config_dir=config_dir, database_path=db_path, **arguments)
    assert recreated["team_id"] == first["team_id"] == "reusable-team"
    assert get_active_team_id(config_dir) == "reusable-team"


@pytest.mark.parametrize("explicit_id", [False, True])
def test_failed_create_can_retry_same_team_id(teams_test_env, monkeypatch, explicit_id):
    from fpl_manager import teams
    config_dir, db_path = teams_test_env
    ensure_teams_initialized(config_dir)
    original_write = teams.write_state_text
    def fail_metadata(path, text):
        if path.parent.name == "retry-team" and path.name == "metadata.json":
            raise OSError("injected team metadata failure")
        return original_write(path, text)
    arguments = {"team_id": "retry-team"} if explicit_id else {}
    with monkeypatch.context() as patch:
        patch.setattr(teams, "write_state_text", fail_metadata)
        with pytest.raises(OSError, match="injected"):
            create_team("Retry Team", config_dir=config_dir, database_path=db_path, **arguments)
    leftover = config_dir / "teams" / "retry-team"
    assert leftover.is_dir()
    assert not (leftover / "squad.json").exists()
    assert not (leftover / "metadata.json").exists()
    retried = create_team("Retry Team", config_dir=config_dir, database_path=db_path, **arguments)
    assert retried["team_id"] == "retry-team"


def test_workspace_existence_honors_staged_metadata(teams_test_env):
    from fpl_manager.application import CommandBus, LiveContext
    from fpl_manager.application.files import delete_state_file, write_state_text
    from fpl_manager.teams import team_workspace_exists
    config_dir, db_path = teams_test_env
    metadata = config_dir / "teams" / "reserved" / "metadata.json"
    def action():
        assert not team_workspace_exists("reserved", config_dir)
        write_state_text(metadata, '{"team_id": "reserved"}')
        assert team_workspace_exists("reserved", config_dir)
        delete_state_file(metadata)
        assert not team_workspace_exists("reserved", config_dir)
        return {}
    CommandBus(db_path).execute(LiveContext("reserved", "2026/27", 2), "fixture", {}, action)
    assert not metadata.exists()


@pytest.mark.parametrize("source", ["legacy", "example"])
@pytest.mark.parametrize("content", ["{", '{"player_ids": []}'])
def test_invalid_initial_squad_raises_actionable_error(teams_test_env, source, content):
    config_dir, _ = teams_test_env
    legacy = config_dir / "current_squad.json"
    initial = legacy if source == "legacy" else config_dir / "current_squad.example.json"
    if source == "example":
        legacy.unlink()
    initial.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="Cannot initialize teams.*Repair"):
        ensure_teams_initialized(config_dir)
    assert initial.read_text(encoding="utf-8") == content
    assert not (config_dir / "teams" / "default" / "squad.json").exists()
    assert not (config_dir / "active_team.json").exists()


@pytest.mark.parametrize("content", [
    "{", "[]", "{}", '{"active_team_id": null}', '{"active_team_id": 17}',
    '{"active_team_id": "../other"}',
])
def test_corrupt_active_team_pointer_never_falls_back_to_default(teams_test_env, content):
    config_dir, _ = teams_test_env
    active = config_dir / "active_team.json"
    active.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid active team.*Repair"):
        get_active_team_id(config_dir)
    with pytest.raises(ValueError, match="Invalid active team.*Repair"):
        ensure_teams_initialized(config_dir)
    assert active.read_text(encoding="utf-8") == content
    assert not (config_dir / "teams" / "default" / "squad.json").exists()


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

    # 5. fpl team rename
    main(["team", "rename", "Team Marco", "--id", "default"])
    out, _ = capsys.readouterr()
    assert "Renamed team 'default' to 'Team Marco'." in out

    # 6. fpl team delete league-winner
    main(["team", "delete", "league-winner"])
    out, _ = capsys.readouterr()
    assert "Deleted team 'league-winner'. Active team is now 'default'." in out


def test_rename_team(teams_test_env: tuple[Path, Path]) -> None:
    config_dir, _ = teams_test_env
    ensure_teams_initialized(config_dir)

    # Rename default team
    renamed = rename_team("default", "Team Marco", config_dir=config_dir)
    assert renamed["name"] == "Team Marco"
    assert renamed["team_id"] == "default"

    # Verify reflected in list_teams
    teams = list_teams(config_dir)
    default_meta = next(t for t in teams if t["team_id"] == "default")
    assert default_meta["name"] == "Team Marco"

    # Validation errors
    with pytest.raises(ValueError, match="Team name cannot be empty"):
        rename_team("default", "   ", config_dir=config_dir)

    with pytest.raises(ValueError, match="not found"):
        rename_team("nonexistent-team", "New Name", config_dir=config_dir)
