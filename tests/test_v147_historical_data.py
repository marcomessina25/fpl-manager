"""V1.4.7 historical execution and truthful dataset-validation regressions."""

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path

import pytest

from fpl_manager.errors import DataIntegrityError
from fpl_manager.execution import ExecutionVersion, execution_scope
from fpl_manager.historical.ingestion import generate_mock_season, parse_gw_csv
from fpl_manager.historical.models import GameweekOutcome, Position
from fpl_manager.historical.snapshots import load_gameweek_outcomes
from fpl_manager.historical.validation import validate_season_dataset


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _season(tmp_path: Path) -> Path:
    path = tmp_path / "2023-24"
    generate_mock_season(path, num_gameweeks=2, num_teams=4)
    return path


def _double_rows(path: Path) -> list[dict]:
    rows = json.loads((path / "gws" / "gw1.json").read_text(encoding="utf-8"))
    first = dict(rows[0], fixture_id=1, minutes=67, total_points=16, starts=1,
                 goals_scored=2, assists=1, clean_sheets=0, goals_conceded=1, bonus=3, bps=63)
    second = dict(first, fixture_id=99, opponent_team_id=3, minutes=90, total_points=13,
                  assists=0, clean_sheets=1, goals_conceded=0, bps=52)
    fixtures_path = path / "fixtures.json"
    fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))
    fixtures.append(dict(fixtures[0], fixture_id=99, team_a=3))
    _write(fixtures_path, fixtures)
    _write(path / "gws" / "gw1.json", [first, second])
    return [first, second]


def test_dgw_aggregates_all_statistics_and_immutable_fixture_provenance(tmp_path: Path) -> None:
    path = _season(tmp_path)
    rows = _double_rows(path)
    result = load_gameweek_outcomes(path, 1)[1]
    assert (result.total_points, result.minutes, result.starts) == (29, 157, 2)
    assert (result.goals_scored, result.assists, result.clean_sheets,
            result.goals_conceded, result.bonus, result.bps) == (4, 1, 1, 1, 6, 115)
    assert result.was_home is None and result.opponent_team_id is None
    assert tuple(f.fixture_id for f in result.fixture_outcomes) == (1, 99)
    assert tuple(f.total_points for f in result.fixture_outcomes) == (16, 13)
    with pytest.raises(FrozenInstanceError):
        result.fixture_outcomes[0].minutes = 0
    _write(path / "gws" / "gw1.json", list(reversed(rows)))
    assert load_gameweek_outcomes(path, 1)[1] == result


def test_legacy_outcomes_keep_last_fixture_and_context_selects_policy(tmp_path: Path) -> None:
    path = _season(tmp_path)
    rows = _double_rows(path)
    legacy = load_gameweek_outcomes(path, 1, execution_version="v146")[1]
    assert (legacy.total_points, legacy.minutes) == (13, 90)
    with execution_scope(ExecutionVersion.LEGACY_V146):
        assert load_gameweek_outcomes(path, 1)[1] == legacy
        assert load_gameweek_outcomes(path, 1, execution_version="v147")[1].total_points == 29
    _write(path / "gws" / "gw1.json", list(reversed(rows)))
    assert load_gameweek_outcomes(path, 1, execution_version="v146")[1].total_points == 16
    assert load_gameweek_outcomes(path, 1)[1].total_points == 29


@pytest.mark.parametrize("kind", ["duplicate", "ambiguous", "mixed"])
def test_corrected_outcomes_reject_duplicate_or_unidentified_multirows(tmp_path: Path, kind: str) -> None:
    path = _season(tmp_path)
    rows = _double_rows(path)
    if kind == "duplicate":
        rows[1] = dict(rows[0])
    elif kind == "ambiguous":
        rows = [{"player_id": 1, "minutes": 90, "total_points": 2}] * 2
    else:
        rows[1] = {"player_id": 1, "minutes": 0, "total_points": 0}
    _write(path / "gws" / "gw1.json", rows)
    with pytest.raises(DataIntegrityError, match="fixture"):
        load_gameweek_outcomes(path, 1)


def test_single_legacy_record_without_fixture_identity_remains_supported(tmp_path: Path) -> None:
    path = _season(tmp_path)
    _write(path / "gws" / "gw1.json", [{"player_id": 5, "minutes": 20, "total_points": 1}])
    outcome = load_gameweek_outcomes(path, 1)[5]
    assert outcome.minutes == 20
    assert len(outcome.fixture_outcomes) == 1
    assert outcome.fixture_outcomes[0].fixture_id is None


@pytest.mark.parametrize("asset,value", [
    ("season_manifest.json", "{bad json"),
    ("season_manifest.json", "[]"),
    ("fixtures.json", "{bad json"),
    ("gws/gw1.json", "{bad json"),
    ("gws/gw1.json", '[{"player_id":1,"minutes":"90","total_points":2}]'),
    ("gws/gw1.json", '[{"player_id":1,"minutes":-1,"total_points":2}]'),
])
def test_corrected_outcome_corruption_raises_typed_integrity_error(
    tmp_path: Path, asset: str, value: str,
) -> None:
    path = _season(tmp_path)
    path.joinpath(*asset.split("/")).write_text(value, encoding="utf-8")
    with pytest.raises(DataIntegrityError):
        load_gameweek_outcomes(path, 1)


@pytest.mark.parametrize("chip,multiplier", [(None, 2), ("triple_captain", 3)])
def test_dgw_played_then_dnp_does_not_promote_captain_or_autosub(
    tmp_path: Path, chip: str | None, multiplier: int,
) -> None:
    from fpl_manager.backtest.engine import simulate_autosubs_and_score

    path = _season(tmp_path)
    rows = _double_rows(path)
    rows[1] = dict(rows[1], minutes=0, total_points=0, starts=0)
    _write(path / "gws" / "gw1.json", rows)
    outcomes = {
        pid: GameweekOutcome("2023-24", 1, pid, 90, 2)
        for pid in range(1, 16)
    }
    outcomes[1] = load_gameweek_outcomes(path, 1)[1]
    positions = dict(zip(range(1, 16), [
        Position.FORWARD, Position.GOALKEEPER,
        *[Position.DEFENDER] * 4, *[Position.MIDFIELDER] * 4, Position.FORWARD,
        Position.FORWARD, Position.DEFENDER, Position.MIDFIELDER, Position.GOALKEEPER,
    ]))
    score, autosubs, promoted = simulate_autosubs_and_score(
        list(range(1, 12)), list(range(12, 16)), 1, 7, outcomes, positions, chip_used=chip,
    )
    assert (score, autosubs, promoted) == (20 + 16 * multiplier, (), False)
    outcomes[1] = replace(outcomes[1], minutes=157, total_points=29)
    score, autosubs, promoted = simulate_autosubs_and_score(
        list(range(1, 12)), list(range(12, 16)), 1, 7, outcomes, positions, chip_used=chip,
    )
    assert (score, autosubs, promoted) == (20 + 29 * multiplier, (), False)


def test_public_mateta_gw34_aggregates_without_rewriting_source() -> None:
    path = Path(__file__).resolve().parents[1] / "data" / "historical" / "2023-24"
    if not (path / "gws" / "gw34.json").exists():
        pytest.skip("Public historical season not installed")
    assets = [path / "season_manifest.json", path / "fixtures.json", path / "gws" / "gw34.json"]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in assets}
    corrected = load_gameweek_outcomes(path, 34)[232]
    legacy = load_gameweek_outcomes(path, 34, execution_version="v146")[232]
    assert (corrected.total_points, corrected.minutes) == (29, 157)
    assert (legacy.total_points, legacy.minutes) == (13, 90)
    assert len({f.fixture_id for f in corrected.fixture_outcomes}) == 2
    assert all(f.fixture_id is not None for f in corrected.fixture_outcomes)
    assert before == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in assets}


def test_ingestion_preserves_explicit_fixture_identity(tmp_path: Path) -> None:
    csv_path = tmp_path / "gw1.csv"
    csv_path.write_text(
        "element,name,position,team,value,minutes,total_points,fixture\n"
        "232,Mateta,FWD,8,50,67,16,334\n"
        "232,Mateta,FWD,8,50,90,13,335\n",
        encoding="utf-8",
    )
    assert [r["fixture_id"] for r in parse_gw_csv(csv_path)] == [334, 335]


@pytest.mark.parametrize("asset", ["teams.json", "fixtures.json", "gws/gw2.json"])
def test_dataset_missing_required_assets_fail(tmp_path: Path, asset: str) -> None:
    path = _season(tmp_path)
    path.joinpath(*asset.split("/")).unlink()
    report = validate_season_dataset(path)
    assert report["valid"] is False
    assert report["stages"]["availability"]["status"] == "failed"


@pytest.mark.parametrize("asset,value", [
    ("season_manifest.json", "{bad json"),
    ("teams.json", "{}"),
    ("fixtures.json", "[null]"),
    ("gws/gw1.json", "[true]"),
    ("gws/gw1.json", '[{"player_id":1,"minutes":NaN}]'),
])
def test_dataset_corrupt_json_and_types_report_failure(tmp_path: Path, asset: str, value: str) -> None:
    path = _season(tmp_path)
    path.joinpath(*asset.split("/")).write_text(value, encoding="utf-8")
    report = validate_season_dataset(path)
    assert report["valid"] is False
    assert report["stages"]["schema"]["status"] == "failed"
    assert report["issues"]


@pytest.mark.parametrize("kind", ["team", "opponent", "fixture", "duplicate_fixture", "duplicate_player"])
def test_dataset_reference_and_duplicate_errors_fail(tmp_path: Path, kind: str) -> None:
    path = _season(tmp_path)
    rows = _double_rows(path)
    if kind == "team":
        rows[0]["team_id"] = 100
    elif kind == "opponent":
        rows[0]["opponent_team_id"] = 100
    elif kind == "fixture":
        rows[0]["fixture_id"] = 100
    elif kind == "duplicate_player":
        rows[1] = dict(rows[0])
    else:
        fixtures = json.loads((path / "fixtures.json").read_text(encoding="utf-8"))
        _write(path / "fixtures.json", fixtures + [fixtures[0]])
    _write(path / "gws" / "gw1.json", rows)
    report = validate_season_dataset(path)
    assert report["valid"] is False
    assert report["stages"]["references"]["status"] == "failed"


@pytest.mark.parametrize("kind", ["unknown_pair", "conflicting_aliases", "opponent_without_home"])
def test_fixture_reference_metadata_cannot_silently_disagree(tmp_path: Path, kind: str) -> None:
    path = _season(tmp_path)
    rows = json.loads((path / "gws" / "gw1.json").read_text(encoding="utf-8"))
    if kind == "unknown_pair":
        rows[0]["opponent_team_id"] = 3
    elif kind == "conflicting_aliases":
        rows[0].update(fixture_id=1, fixture=2)
    else:
        rows[0].update(fixture_id=1, opponent_team_id=3)
        del rows[0]["was_home"]
    _write(path / "gws" / "gw1.json", rows)
    report = validate_season_dataset(path)
    assert report["valid"] is False
    assert report["stages"]["references"]["status"] == "failed"


@pytest.mark.parametrize("field,value", [
    ("total_gameweeks", True), ("total_gameweeks", 2.5), ("deadlines", []),
])
def test_manifest_invalid_schema_is_reported(tmp_path: Path, field: str, value: object) -> None:
    path = _season(tmp_path)
    manifest_path = path / "season_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = value
    _write(manifest_path, manifest)
    assert validate_season_dataset(path)["valid"] is False


@pytest.mark.parametrize("asset,field", [
    ("fixtures.json", "team_h_score"), ("teams.json", "strength"),
])
def test_all_assets_reject_nonfinite_numbers(tmp_path: Path, asset: str, field: str) -> None:
    path = _season(tmp_path)
    asset_path = path / asset
    rows = json.loads(asset_path.read_text(encoding="utf-8"))
    rows[0][field] = float("inf")
    _write(asset_path, rows)
    report = validate_season_dataset(path)
    assert report["valid"] is False
    assert report["source_digests"][str(asset_path)] == hashlib.sha256(asset_path.read_bytes()).hexdigest()


def test_mock_generator_longer_partial_season_has_valid_timestamps(tmp_path: Path) -> None:
    path = tmp_path / "2023-24"
    generate_mock_season(path, num_gameweeks=12, num_teams=4)
    report = validate_season_dataset(path)
    assert report["valid"] is True, report["issues"]


def test_valid_dgw_has_truthful_evidence_stages_and_actual_source_digests(tmp_path: Path) -> None:
    path = _season(tmp_path)
    _double_rows(path)
    report = validate_season_dataset(path)
    assert report["valid"] is True, report
    assert report["gameweeks_verified"] == 2
    assert report["stages"]["schema"]["status"] == "passed"
    assert report["stages"]["references"]["status"] == "passed"
    assert report["point_in_time_evidence"]["fixture_announcements"]["status"] == "not_available"
    assert report["point_in_time_evidence"]["deadline_provenance"]["status"] == "not_available"
    assert report["point_in_time_evidence"]["score_masking"]["status"] == "not_checked"
    fixture_path = path / "fixtures.json"
    assert report["source_digests"][str(fixture_path)] == hashlib.sha256(fixture_path.read_bytes()).hexdigest()


@pytest.mark.parametrize("content", ["{bad json", "[]", '{"2023-24": []}'])
def test_global_or_affected_registry_corruption_fails_dataset(tmp_path: Path, content: str) -> None:
    path = _season(tmp_path)
    (path.parent / "unavailability_registry.json").write_text(content, encoding="utf-8")
    report = validate_season_dataset(path)
    assert report["valid"] is False
    assert any("registry" in issue.lower() for issue in report["issues"])


def test_other_season_registry_problem_does_not_fail_valid_season(tmp_path: Path) -> None:
    path = _season(tmp_path)
    _write(path.parent / "unavailability_registry.json", {"2022-23": []})
    report = validate_season_dataset(path)
    assert report["valid"] is True, report


@pytest.mark.parametrize("start", [True, 1.5, float("inf")])
def test_registry_noninteger_window_is_rejected_without_fallback(tmp_path: Path, start: object) -> None:
    from fpl_manager.historical.snapshots import load_unavailability_registry

    path = _season(tmp_path)
    _write(path.parent / "unavailability_registry.json", {
        "2023-24": {"1": {"start_gw": start, "end_gw": 2, "known_from": "2023-08-31"}},
    })
    with pytest.raises(ValueError, match="non-integer"):
        load_unavailability_registry(path.parent)
    assert validate_season_dataset(path)["valid"] is False
