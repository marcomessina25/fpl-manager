"""Integration tests for the V1.1 Strategic Squad CLI commands."""

import json
from pathlib import Path
import pytest

from fpl_manager.cli import main
from fpl_manager.storage import SnapshotStore
from fpl_manager.teams import create_team, get_team_squad_path, set_active_team

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "fpl.sqlite3"


@pytest.fixture
def cli_test_team():
    """Create and activate an isolated test team for CLI tests, cleaning up before and after."""
    from fpl_manager.teams import delete_team
    try:
        delete_team("cli_strategic_test")
    except Exception:
        pass
    team_info = create_team("CLI Strategic Test Team", team_id="cli_strategic_test", set_as_active=True)
    yield team_info
    try:
        set_active_team("default")
        delete_team("cli_strategic_test")
    except Exception:
        pass


def test_cli_strategic_squad_initial(capsys, cli_test_team, tmp_path):
    """Test strategic-squad command for initial squad generation."""
    out_file = tmp_path / "strategic_initial.json"
    main(["strategic-squad", "--mode", "initial", "--strategy", "balanced", "--horizon", "3", "--output", str(out_file)])
    captured = capsys.readouterr()
    assert "=== Strategic Squad Studio (V1.1)" in captured.out
    assert "Starting 11:" in captured.out
    assert "Bench:" in captured.out
    assert out_file.exists()

    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["mode"] == "initial"
    assert data["strategy"] == "balanced"
    assert len(data["selected_candidate"]["player_ids"]) == 15


def test_cli_strategic_squad_with_constraints_and_compare(capsys, cli_test_team, tmp_path):
    """Test strategic squad optimization with locks, exclusions, preferences, and opportunity cost diff."""
    base_file = tmp_path / "base_squad.json"
    main(["strategic-squad", "--mode", "initial", "--strategy", "balanced", "--horizon", "3", "--output", str(base_file)])
    assert base_file.exists()
    base_data = json.loads(base_file.read_text(encoding="utf-8"))
    cand = base_data["selected_candidate"]
    starter_to_lock = cand["starters"][0]["id"]
    bench_to_exclude = cand["bench"][0]["id"]

    # Re-run with lock, exclusion, and comparison
    reopt_file = tmp_path / "reopt_squad.json"
    main([
        "strategic-squad",
        "--mode", "initial",
        "--strategy", "balanced",
        "--horizon", "3",
        "--lock", str(starter_to_lock),
        "--exclude", str(bench_to_exclude),
        "--compare-with", str(base_file),
        "--output", str(reopt_file),
    ])
    captured = capsys.readouterr()
    assert "Constraint Impact Analysis:" in captured.out
    assert "Opportunity Cost:" in captured.out

    reopt_data = json.loads(reopt_file.read_text(encoding="utf-8"))
    assert starter_to_lock in reopt_data["selected_candidate"]["player_ids"]
    assert bench_to_exclude not in reopt_data["selected_candidate"]["player_ids"]
    assert "constraint_impact" in reopt_data
    assert reopt_data["constraint_impact"] is not None


def test_cli_strategic_squad_apply(capsys, cli_test_team, tmp_path):
    """Test applying a strategic squad to the active team via CLI."""
    out_file = tmp_path / "applied_squad.json"
    main([
        "strategic-squad",
        "--mode", "initial",
        "--team", "cli_strategic_test",
        "--apply",
        "--output", str(out_file),
    ])
    captured = capsys.readouterr()
    assert "Applied strategic initial squad to team 'cli_strategic_test'" in captured.out

    squad_path = get_team_squad_path("cli_strategic_test")
    assert squad_path.exists()
    saved_squad = json.loads(squad_path.read_text(encoding="utf-8"))
    assert len(saved_squad.get("player_ids", [])) == 15


def test_cli_backtest_strategic_smoke(capsys, tmp_path):
    """Test running backtest-strategic CLI command in smoke mode."""
    out_dir = tmp_path / "reports_v11"
    main([
        "backtest-strategic",
        "--suite", "profiles",
        "--season", "2023-24",
        "--smoke",
        "--output-dir", str(out_dir),
    ])
    captured = capsys.readouterr()
    assert "Strategic profiles report saved to:" in captured.out
    assert (out_dir / "strategic_profiles_2023-24.md").exists()
    assert (out_dir / "strategic_profiles_2023-24.json").exists()
