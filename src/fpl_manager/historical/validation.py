"""Staged historical asset validation and scoped snapshot leakage checks."""

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from ..errors import DataIntegrityError
from .models import GameweekOutcome, HistoricalGameweekSnapshot, Position


def validate_snapshot_integrity(snapshot: HistoricalGameweekSnapshot) -> list[str]:
    """Validate that a point-in-time snapshot contains legal, uncorrupted domain data."""
    issues: list[str] = []

    if not snapshot.players:
        issues.append("Snapshot contains zero players.")
        return issues

    if not snapshot.teams or len(snapshot.teams) < 2:
        issues.append(f"Snapshot teams list is invalid (count: {len(snapshot.teams)}).")

    team_ids = {t["team_id"] for t in snapshot.teams}

    positions_found: set[Position] = set()
    for p in snapshot.players:
        positions_found.add(p.position)
        # Price validation: between £3.5m (35) and £16.0m (160)
        if p.price_tenths < 35 or p.price_tenths > 160:
            issues.append(f"Player {p.player_id} ({p.web_name}) has out-of-bounds price {p.price_tenths / 10.0}m.")

        # Non-negative cumulative metrics
        if p.minutes < 0:
            issues.append(f"Player {p.player_id} has negative minutes: {p.minutes}.")
        if p.starts < 0:
            issues.append(f"Player {p.player_id} has negative starts: {p.starts}.")
        if p.total_points < 0 and snapshot.gameweek == 1:
            issues.append(f"Player {p.player_id} has negative points at GW1: {p.total_points}.")

        if p.team_id not in team_ids:
            issues.append(f"Player {p.player_id} references unknown team_id: {p.team_id}.")

    for required_pos in Position:
        if required_pos not in positions_found:
            issues.append(f"Missing position {required_pos.name} from player pool.")

    return issues


PIT_LEAKAGE_VERIFICATION_SCOPE: dict[str, Any] = {
    "intrinsic_snapshot_invariants": {
        "description": (
            "Invariants checked directly from the snapshot alone without external reference inputs."
        ),
        "categories": [
            "6_future_fixtures_or_results (finished=True or revealed match scores in target GW)",
            "7_later_versions_of_statistics (cumulative starts/minutes/starts_last_3 exceeding finished_gameweeks physical bounds; non-zero cumulative stats at GW1)",
        ],
    },
    "reference_comparative_checks": {
        "description": (
            "Differential checks that verify a snapshot against an explicitly supplied pre/post-deadline reference state (prior_snapshot, outcomes, or post_deadline_state)."
        ),
        "categories": [
            "1_final_gw_statistics (requires prior_snapshot and outcomes to detect absorbed target-GW points)",
            "2_future_injury_information (requires post_deadline_state['pre_deadline_status'] / ['future_status'])",
            "3_future_price_changes (requires post_deadline_state['pre_deadline_price_tenths'] / ['future_price_tenths'])",
            "4_future_ownership (requires post_deadline_state['pre_deadline_ownership'] / ['future_ownership'])",
            "5_post_deadline_team_news (requires post_deadline_state['news_timestamp'] / ['deadline_timestamp'])",
        ],
    },
}


def validate_no_future_leakage(
    snapshot: HistoricalGameweekSnapshot,
    outcomes: dict[int, GameweekOutcome],
    prior_snapshot: HistoricalGameweekSnapshot | None = None,
    post_deadline_state: dict[int, dict[str, Any]] | None = None,
) -> list[str]:
    """Verify that a snapshot contains no knowledge of current or future gameweek outcomes (P1.1, P1.4).

    Scope & Verification Semantics (P1.4 — see `PIT_LEAKAGE_VERIFICATION_SCOPE`):
    - Intrinsic Snapshot Invariants (verified directly from `snapshot` alone):
      * Category 6: Target-GW fixtures marked `finished=True` or containing revealed `team_h_score`/`team_a_score`.
      * Category 7: Cumulative `starts`, `minutes`, or `starts_last_3` exceeding `snapshot.finished_gameweeks` bounds (or non-zero at GW1).
    - Reference-Comparative Checks (verified when `prior_snapshot`, `outcomes`, or `post_deadline_state` is supplied):
      * Category 1: Final GW points absorbed into `total_points` (requires `prior_snapshot` + `outcomes`).
      * Categories 2-5: Post-deadline injury status, price changes, ownership, or news timestamps (requires `post_deadline_state`).

    An empty violation list is not proof of historical as-of provenance when those
    reference inputs or fixture-announcement timestamps are unavailable.
    """
    leakage_violations: list[str] = []
    max_possible_starts = max(0, int(snapshot.finished_gameweeks))
    max_possible_minutes = max_possible_starts * 120  # upper bound including potential double GWs

    # Protection 6: Future fixtures / results
    for fix in snapshot.fixtures:
        if getattr(fix, "finished", False):
            leakage_violations.append(
                f"Leakage in GW{snapshot.gameweek} fixtures: Fixture {fix.fixture_id} is already marked finished."
            )
        if getattr(fix, "team_h_score", None) is not None or getattr(fix, "team_a_score", None) is not None:
            leakage_violations.append(
                f"Leakage in GW{snapshot.gameweek} fixtures: Fixture {fix.fixture_id} contains revealed match scores."
            )

    if snapshot.gameweek == 1:
        for p in snapshot.players:
            if p.minutes != 0:
                leakage_violations.append(
                    f"Leakage in GW1: Player {p.player_id} has non-zero prior minutes ({p.minutes})."
                )
            if p.total_points != 0:
                leakage_violations.append(
                    f"Leakage in GW1: Player {p.player_id} has non-zero prior points ({p.total_points})."
                )
            if p.starts != 0:
                leakage_violations.append(
                    f"Leakage in GW1: Player {p.player_id} has non-zero prior starts ({p.starts})."
                )
    else:
        prior_by_id = (
            {pp.player_id: pp for pp in prior_snapshot.players}
            if prior_snapshot is not None
            else {}
        )
        for p in snapshot.players:
            # Protection 7: Later versions of statistics exceeding completed gameweeks
            if p.starts > max_possible_starts * 2:
                leakage_violations.append(
                    f"Later-stat leakage in GW{snapshot.gameweek}: Player {p.player_id} starts ({p.starts}) exceed completed GWs ({max_possible_starts})."
                )
            if p.minutes > max_possible_minutes:
                leakage_violations.append(
                    f"Later-stat leakage in GW{snapshot.gameweek}: Player {p.player_id} minutes ({p.minutes}) exceed max possible ({max_possible_minutes})."
                )
            if p.starts_last_3 > min(6, max_possible_starts * 2):
                leakage_violations.append(
                    f"Later-stat leakage in GW{snapshot.gameweek}: Player {p.player_id} starts_last_3 ({p.starts_last_3}) exceeds completed history."
                )

            # Protection 1: Final GW statistics leaked into pre-deadline snapshot
            outcome = outcomes.get(p.player_id)
            if outcome is not None and p.player_id in prior_by_id:
                prev_p = prior_by_id[p.player_id]
                # If snapshot total_points already includes both prev GW and current GW outcome points:
                if outcome.total_points > 0 and p.total_points > prev_p.total_points + outcome.total_points - 1 and snapshot.finished_gameweeks == prior_snapshot.finished_gameweeks:
                    leakage_violations.append(
                        f"Final-GW stat leakage in GW{snapshot.gameweek}: Player {p.player_id} includes current GW points ({p.total_points})."
                    )

            # Protections 2, 3, 4, 5: Future injury, price, ownership, and post-deadline news
            if post_deadline_state and p.player_id in post_deadline_state:
                post = post_deadline_state[p.player_id]
                if "pre_deadline_status" in post and p.status != post["pre_deadline_status"] and p.status == post.get("future_status"):
                    leakage_violations.append(
                        f"Future injury leakage in GW{snapshot.gameweek}: Player {p.player_id} has future status '{p.status}' instead of pre-deadline '{post['pre_deadline_status']}'."
                    )
                if "pre_deadline_price_tenths" in post and p.price_tenths != post["pre_deadline_price_tenths"] and p.price_tenths == post.get("future_price_tenths"):
                    leakage_violations.append(
                        f"Future price leakage in GW{snapshot.gameweek}: Player {p.player_id} has future price {p.price_tenths} instead of {post['pre_deadline_price_tenths']}."
                    )
                if "pre_deadline_ownership" in post:
                    cur_own = getattr(p, "selected_by_percent", None)
                    if cur_own is not None and abs(cur_own - post["pre_deadline_ownership"]) > 1e-6 and abs(cur_own - post.get("future_ownership", -1.0)) < 1e-6:
                        leakage_violations.append(
                            f"Future ownership leakage in GW{snapshot.gameweek}: Player {p.player_id} has future ownership {cur_own}."
                        )
                if "news_timestamp" in post and "deadline_timestamp" in post:
                    if str(post["news_timestamp"]) > str(post["deadline_timestamp"]):
                        leakage_violations.append(
                            f"Post-deadline news leakage in GW{snapshot.gameweek}: Player {p.player_id} news timestamp {post['news_timestamp']} > deadline {post['deadline_timestamp']}."
                        )

    return leakage_violations


def _read_validation_asset(
    path: Path,
    availability_issues: list[str],
    schema_issues: list[str],
    digests: dict[str, str],
) -> Any:
    """Read once, recording the digest of the bytes actually parsed, including invalid JSON."""
    try:
        content = path.read_bytes()
    except OSError as exc:
        availability_issues.append(f"Missing or unreadable asset {path}: {exc}")
        return None
    digests[str(path)] = hashlib.sha256(content).hexdigest()
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        schema_issues.append(f"Invalid JSON in {path}: {exc}")
        return None
    _validate_finite_numbers(value, str(path), schema_issues)
    return value


def _validate_finite_numbers(value: Any, label: str, issues: list[str]) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        issues.append(f"{label}: numbers must be finite.")
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_finite_numbers(item, f"{label}.{key}", issues)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_finite_numbers(item, f"{label}[{index}]", issues)


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("expected an ISO-8601 date/timestamp string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _validate_deadlines(value: Any, label: str, issues: list[str]) -> dict[int, datetime]:
    if not isinstance(value, dict):
        issues.append(f"{label}: deadlines must be a JSON object.")
        return {}
    deadlines: dict[int, datetime] = {}
    for gw, deadline in value.items():
        try:
            gw_num = int(gw)
            if str(gw_num) != str(gw) or not 1 <= gw_num <= 38:
                raise ValueError("gameweek must be an integer from 1 to 38")
            deadlines[gw_num] = _timestamp(deadline)
        except (ValueError, TypeError) as exc:
            issues.append(f"{label}: invalid deadline for GW{gw}: {exc}")
    return deadlines


def _validate_records_schema(
    value: Any, label: str, kind: str, issues: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        issues.append(f"{label}: expected a JSON list of {kind} objects.")
        return []
    records: list[dict[str, Any]] = []
    required_ints = {
        "teams": ("team_id",),
        "fixtures": ("fixture_id", "team_h", "team_a"),
        "players": ("player_id", "position", "team_id", "price_tenths", "minutes", "total_points"),
    }[kind]
    optional_ints = {
        "teams": ("strength", "strength_overall_home", "strength_overall_away"),
        "fixtures": ("team_h_difficulty", "team_a_difficulty"),
        "players": ("fixture_id", "fixture", "starts", "goals_scored", "assists", "clean_sheets",
                    "goals_conceded", "bonus", "bps", "opponent_team_id"),
    }[kind]
    required_strings = {"teams": ("name", "short_name"), "fixtures": (), "players": ("name",)}[kind]
    for index, row in enumerate(value):
        row_label = f"{label}[{index}]"
        if not isinstance(row, dict):
            issues.append(f"{row_label}: expected a JSON object.")
            continue
        records.append(row)
        for field in required_ints + optional_ints:
            if field not in row and field not in required_ints:
                continue
            number = row.get(field)
            if type(number) is not int:
                issues.append(f"{row_label}.{field}: expected an integer.")
            elif field not in ("total_points", "bps") and number < 0:
                issues.append(f"{row_label}.{field}: must not be negative.")
            elif field in ("team_id", "player_id", "fixture_id", "fixture", "team_h", "team_a", "price_tenths") and number == 0:
                issues.append(f"{row_label}.{field}: must be positive.")
        for field in required_strings:
            if not isinstance(row.get(field), str) or not row[field]:
                issues.append(f"{row_label}.{field}: expected a non-empty string.")
        if kind == "players":
            if type(row.get("position")) is int and row["position"] not in (1, 2, 3, 4):
                issues.append(f"{row_label}.position: must be 1, 2, 3 or 4.")
            for field in ("selected", "expected_goals", "expected_assists", "expected_goal_involvements",
                          "expected_goals_conceded", "ict_index"):
                if field in row and type(row[field]) not in (int, float):
                    issues.append(f"{row_label}.{field}: expected a finite number.")
            if "was_home" in row and type(row["was_home"]) is not bool:
                issues.append(f"{row_label}.was_home: expected a boolean.")
            for field in ("chance_of_playing_this_round", "chance_of_playing_next_round"):
                chance = row.get(field)
                if chance is not None and (type(chance) is not int or not 0 <= chance <= 100):
                    issues.append(f"{row_label}.{field}: expected null or an integer from 0 to 100.")
            for field in ("status", "news"):
                if field in row and not isinstance(row[field], str):
                    issues.append(f"{row_label}.{field}: expected a string.")
        elif kind == "fixtures":
            event = row.get("event")
            if "event" not in row or (event is not None and (type(event) is not int or not 1 <= event <= 38)):
                issues.append(f"{row_label}.event: expected null or a gameweek from 1 to 38.")
            for field in ("team_h_difficulty", "team_a_difficulty"):
                if type(row.get(field)) is int and not 1 <= row[field] <= 5:
                    issues.append(f"{row_label}.{field}: expected a difficulty from 1 to 5.")
            if "finished" in row and not (
                type(row["finished"]) is bool or (type(row["finished"]) is int and row["finished"] in (0, 1))
            ):
                issues.append(f"{row_label}.finished: expected a boolean or 0/1.")
            for field in ("team_h_score", "team_a_score"):
                score = row.get(field)
                if score is not None and (type(score) is not int or score < 0):
                    issues.append(f"{row_label}.{field}: expected null or a non-negative integer.")
            if row.get("kickoff_time") is not None:
                try:
                    _timestamp(row["kickoff_time"])
                except ValueError as exc:
                    issues.append(f"{row_label}.kickoff_time: {exc}")
    return records


def _validate_references(
    teams: list[dict[str, Any]],
    fixtures: list[dict[str, Any]],
    gameweeks: dict[int, list[dict[str, Any]]],
) -> tuple[list[str], set[int]]:
    from .snapshots import _identify_gameweek_rows

    issues: list[str] = []
    team_ids = {row["team_id"] for row in teams}
    if len(team_ids) != len(teams):
        issues.append("Duplicate team_id in teams.json.")
    fixtures_by_id = {row["fixture_id"]: row for row in fixtures}
    if len(fixtures_by_id) != len(fixtures):
        issues.append("Duplicate fixture identity in fixtures.json.")
    for row in fixtures:
        for field in ("team_h", "team_a"):
            if row[field] not in team_ids:
                issues.append(f"Fixture {row['fixture_id']} references unknown {field}={row[field]}.")
        if row["team_h"] == row["team_a"]:
            issues.append(f"Fixture {row['fixture_id']} has identical home and away teams.")
    verified: set[int] = set()
    for gw, rows in gameweeks.items():
        before = len(issues)
        for row in rows:
            if row["team_id"] not in team_ids:
                issues.append(f"GW{gw} player {row['player_id']} references unknown team_id={row['team_id']}.")
            opponent = row.get("opponent_team_id", 0)
            if opponent != 0 and opponent not in team_ids:
                issues.append(f"GW{gw} player {row['player_id']} references unknown opponent_team_id={opponent}.")
        try:
            identified = _identify_gameweek_rows(rows, fixtures, gw)
        except DataIntegrityError as exc:
            issues.append(str(exc))
            continue
        for pid, group in identified.items():
            for row, fid, _ in group:
                if fid is None:
                    if row.get("opponent_team_id", 0) > 0 and "was_home" in row:
                        issues.append(f"GW{gw} player {pid} references an unknown fixture pairing.")
                    continue
                fixture = fixtures_by_id.get(fid)
                if fixture is None or fixture["event"] != gw:
                    issues.append(f"GW{gw} player {pid} references unknown or wrong-gameweek fixture {fid}.")
                    continue
                if row["team_id"] not in (fixture["team_h"], fixture["team_a"]):
                    issues.append(f"GW{gw} player {pid} team does not participate in fixture {fid}.")
                opponent = row.get("opponent_team_id", 0)
                expected_opponent = fixture["team_a"] if row["team_id"] == fixture["team_h"] else fixture["team_h"]
                if opponent not in (0, expected_opponent):
                    issues.append(f"GW{gw} player {pid} opponent conflicts with fixture {fid}.")
                if "was_home" in row:
                    own, other = ("team_h", "team_a") if row["was_home"] else ("team_a", "team_h")
                    if row["team_id"] != fixture[own] or row.get("opponent_team_id", 0) not in (0, fixture[other]):
                        issues.append(f"GW{gw} player {pid} opponent/home metadata conflicts with fixture {fid}.")
        if len(issues) == before:
            verified.add(gw)
    return issues, verified


def _registry_season_issues(
    registry_path: Path, season: str, entries: Any, manifest: dict[str, Any],
    *, timing_checks: list[dict[str, Any]] | None = None,
) -> list[str]:
    issues: list[str] = []
    if not isinstance(entries, dict):
        return [f"Registry {registry_path}: season '{season}' must map to a JSON object."]
    if not entries:
        return issues
    deadlines = _validate_deadlines(manifest.get("deadlines"), f"Registry season '{season}'", issues)
    chronological = sorted(deadlines.items(), key=lambda item: item[1])
    for pid, entry in entries.items():
        label = f"Registry {registry_path}: season '{season}' player '{pid}'"
        if not str(pid).isdigit() or int(pid) <= 0:
            issues.append(f"{label}: invalid player identity.")
        if not isinstance(entry, dict):
            issues.append(f"{label}: entry must be a JSON object.")
            continue
        start_raw, end_raw = entry.get("start_gw", 1), entry.get("end_gw", 38)
        try:
            if type(start_raw) not in (int, str) or type(end_raw) not in (int, str):
                raise ValueError("start_gw/end_gw must be integers or integer strings")
            start, end = int(start_raw), int(end_raw)
            if not 1 <= start <= end <= 38:
                raise ValueError("must satisfy 1 <= start_gw <= end_gw <= 38")
        except (ValueError, TypeError) as exc:
            issues.append(f"{label}: invalid gameweek window: {exc}")
            continue
        if not isinstance(entry.get("reason", ""), str):
            issues.append(f"{label}: reason must be a string.")
        name = entry.get("name", f"Player {pid}")
        known_from = entry.get("known_from")
        if not known_from:
            issues.append(
                f"Registry leakage check failed for {season} player {pid} ({name}): "
                "missing required 'known_from' date field."
            )
            continue
        try:
            known_dt = _timestamp(known_from)
        except ValueError as exc:
            issues.append(f"{label}: invalid 'known_from' date format '{known_from}': {exc}")
            continue
        first_valid_gw = next((gw for gw, deadline in chronological if deadline > known_dt), None)
        timing = {"season": season, "player_id": str(pid), "known_from": known_from, "start_gw": start}
        if first_valid_gw is None and chronological and start > max(deadlines):
            timing.update(
                status="not_checked",
                reason="Announcement and unavailable window are beyond supplied archive coverage.",
            )
        elif first_valid_gw is None:
            issue = f"{label}: no supplied deadline falls after known_from='{known_from}'."
            issues.append(issue)
            timing.update(status="failed", reason=issue)
        elif start != first_valid_gw:
            issue = (
                f"Registry lookahead leakage in {season} player {pid} ({name}): "
                f"start_gw={start} does not match first post-event deadline gameweek (GW{first_valid_gw}) "
                f"for known_from='{known_from}'."
            )
            issues.append(issue)
            timing.update(status="failed", reason=issue)
        else:
            timing.update(status="passed", first_post_announcement_gameweek=first_valid_gw)
        if timing_checks is not None:
            timing_checks.append(timing)
    return issues


def validate_season_dataset(season_dir: Path) -> dict[str, Any]:
    """Validate availability, JSON/schema and references, not unprovided as-of history.

    Partial seasons need only their declared GW assets; fixtures may cover the full
    season. Manifest counts are descriptive rather than completeness guarantees.
    A passed structural report is NOT evidence that fixture announcements, player
    metadata or nominal deadlines were independently sourced before each deadline.
    """
    availability: list[str] = []
    schema: list[str] = []
    references: list[str] = []
    registry_issues: list[str] = []
    registry_timing: list[dict[str, Any]] = []
    digests: dict[str, str] = {}
    manifest_path = season_dir / "season_manifest.json"
    manifest = _read_validation_asset(manifest_path, availability, schema, digests)
    season: str | None = None
    total_gws: int | None = None
    if not isinstance(manifest, dict):
        schema.append(f"{manifest_path}: manifest must be a JSON object.")
    else:
        season = manifest.get("season")
        total_gws = manifest.get("total_gameweeks")
        if not isinstance(season, str) or not season:
            schema.append(f"{manifest_path}: season must be a non-empty string.")
            season = None
        if type(total_gws) is not int or not 1 <= total_gws <= 38:
            schema.append(f"{manifest_path}: total_gameweeks must be an integer from 1 to 38.")
            total_gws = None
        for field in ("num_players", "num_teams", "num_fixtures"):
            if field in manifest and (type(manifest[field]) is not int or manifest[field] < 0):
                schema.append(f"{manifest_path}.{field}: expected a non-negative integer.")
        deadlines = _validate_deadlines(manifest.get("deadlines"), str(manifest_path), schema)
        if total_gws is not None:
            for gw in range(1, total_gws + 1):
                if gw not in deadlines:
                    schema.append(f"{manifest_path}: missing valid deadline for GW{gw}.")

    teams_path, fixtures_path = season_dir / "teams.json", season_dir / "fixtures.json"
    teams = _validate_records_schema(
        _read_validation_asset(teams_path, availability, schema, digests), str(teams_path), "teams", schema,
    )
    fixtures = _validate_records_schema(
        _read_validation_asset(fixtures_path, availability, schema, digests), str(fixtures_path), "fixtures", schema,
    )
    if not teams:
        schema.append(f"{teams_path}: season must contain teams.")
    gameweeks: dict[int, list[dict[str, Any]]] = {}
    schema_valid_gws: set[int] = set()
    for gw in range(1, (total_gws or 0) + 1):
        gw_path = season_dir / "gws" / f"gw{gw}.json"
        before = (len(availability), len(schema))
        gameweeks[gw] = _validate_records_schema(
            _read_validation_asset(gw_path, availability, schema, digests), str(gw_path), "players", schema,
        )
        if before == (len(availability), len(schema)):
            schema_valid_gws.add(gw)
    references_checked = not availability and not schema
    verified: set[int] = set()
    if references_checked:
        references, verified = _validate_references(teams, fixtures, gameweeks)

    reg_path = season_dir.parent / "unavailability_registry.json"
    if reg_path.exists():
        registry = _read_validation_asset(reg_path, registry_issues, registry_issues, digests)
        if not isinstance(registry, dict):
            registry_issues.append(f"Registry {reg_path} must be a JSON object (global parse/schema failure).")
        elif season is not None and isinstance(manifest, dict):
            registry_issues.extend(_registry_season_issues(
                reg_path, season, registry.get(season, {}), manifest, timing_checks=registry_timing,
            ))

    def stage(issues: list[str], checked: bool = True) -> dict[str, Any]:
        return {"status": "failed" if issues else ("passed" if checked else "not_checked"), "issues": issues}

    issues = availability + schema + references + registry_issues
    report: dict[str, Any] = {
        "valid": not issues,
        "season": season,
        "total_gameweeks": total_gws,
        "gameweeks_verified": len(schema_valid_gws & verified),
        "issues": issues,
        "stages": {
            "availability": stage(availability),
            "schema": stage(schema, checked=not availability),
            "references": stage(references, checked=references_checked),
            "unavailability_registry": stage(registry_issues, checked=reg_path.exists()),
        },
        "source_digests": digests,
        "validation_scope": "Asset availability, schema and referential integrity; not verified historical as-of knowledge.",
        "point_in_time_evidence": {
            "fixture_announcements": {
                "status": "not_available",
                "reason": "No fixture-announcement timestamps/history supplied; the final schedule is not as-of evidence.",
            },
            "deadline_provenance": {
                "status": "not_available",
                "reason": "Manifest deadline syntax is checked, but nominal/derived timestamps are not independently verified FPL deadlines.",
            },
            "player_metadata": {
                "status": "not_available",
                "reason": "Player price, availability and ownership announcement timestamps are not supplied by these normalized assets.",
            },
            "score_masking": {
                "status": "not_checked",
                "reason": "Dataset validation does not exercise snapshot masking; use the separate snapshot leakage checks.",
            },
        },
    }
    if issues:
        report["error"] = issues[0]
    timing_statuses = {check["status"] for check in registry_timing}
    report["stages"]["unavailability_registry"]["deadline_timing"] = {
        "status": (
            "failed" if "failed" in timing_statuses else
            "not_checked" if "not_checked" in timing_statuses or not registry_timing else "passed"
        ),
        "checks": registry_timing,
    }
    return report


def validate_unavailability_registry(registry_path: Path, data_dir: Path) -> list[str]:
    """Check registry structure and timing against supplied nominal deadlines.

    ``known_from`` is curated evidence, not independent proof of an announcement.
    Missing/malformed global registry content must never look like an empty registry.
    """
    issues: list[str] = []
    if not registry_path.exists():
        return issues
    registry = _read_validation_asset(registry_path, issues, issues, {})
    if not isinstance(registry, dict):
        issues.append(f"Registry {registry_path} must be a JSON object.")
        return issues
    for season, entries in registry.items():
        if not isinstance(entries, dict):
            issues.append(f"Registry {registry_path}: season '{season}' must map to a JSON object.")
            continue
        if not entries:
            continue
        manifest_path = data_dir / season / "season_manifest.json"
        manifest = _read_validation_asset(manifest_path, issues, issues, {})
        if not isinstance(manifest, dict):
            issues.append(f"Season manifest for '{season}' must be a JSON object: {manifest_path}")
            continue
        issues.extend(_registry_season_issues(registry_path, season, entries, manifest))
    return issues
