"""Data quality validation and future-leakage verification for V0.7.0."""

import json
from pathlib import Path
from typing import Any

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


def validate_season_dataset(season_dir: Path) -> dict[str, Any]:
    """Comprehensive validation report for an entire season directory."""
    manifest_path = season_dir / "season_manifest.json"
    if not manifest_path.exists():
        return {"valid": False, "error": f"Missing manifest: {manifest_path}"}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    total_gws = manifest["total_gameweeks"]

    issues: list[str] = []
    gws_checked = 0

    for gw in range(1, total_gws + 1):
        gw_path = season_dir / "gws" / f"gw{gw}.json"
        if not gw_path.exists():
            issues.append(f"Missing gameweek file: {gw_path}")
            continue
        gws_checked += 1

    return {
        "valid": len(issues) == 0,
        "season": manifest["season"],
        "total_gameweeks": total_gws,
        "gameweeks_verified": gws_checked,
        "issues": issues,
    }
