"""Current squad report generator for FPL Manager V0.2."""

import json
from pathlib import Path
from typing import Any

from .fixtures import get_current_gameweek
from .models import Position
from .rules import validate_squad
from .squad_state import CurrentSquadState, load_current_squad
from .storage import SnapshotStore
from .transfers import selling_price

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
SQUAD_REPORT_PATH = PROJECT_ROOT / "reports" / "squad_report.json"


def generate_squad_report(
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    report_path: Path = SQUAD_REPORT_PATH,
    gameweek: int | None = None,
    team_id: str | None = None,
) -> dict[str, Any]:
    """Generate a comprehensive report of the manager's current squad state.
    
    If gameweek is provided and has a logged decision, reconstructs the squad representation
    from that point in time.
    """
    state: CurrentSquadState = load_current_squad(squad_path)
    store = SnapshotStore(database_path)

    active_player_ids = state.player_ids
    is_logged = False
    actual_scores: dict[int, float] = {}

    if gameweek is not None:
        try:
            from .decision_log import get_gameweek_decision
            from .scores import get_or_fetch_gameweek_scores
            dec = get_gameweek_decision(gameweek=gameweek, season=state.season, team_id=team_id or "default", database_path=database_path)
            if dec:
                active_player_ids = tuple(dec["starting_player_ids"] + dec["bench_player_ids"])
                is_logged = True
            actual_scores = get_or_fetch_gameweek_scores(gameweek=gameweek, database_path=database_path)
        except Exception:
            pass

    store.initialize()
    with store._connect() as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if snapshot is None:
            raise RuntimeError("No FPL data found. Run `fpl update` first.")
        snapshot_id = snapshot[0]

        # Get team mapping (id -> short_name, name)
        teams_rows = connection.execute(
            "SELECT team_id, short_name, name FROM teams WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        team_map = {row[0]: {"short_name": row[1], "name": row[2]} for row in teams_rows}

        # Query player details
        placeholders = ",".join("?" for _ in active_player_ids)
        player_rows = connection.execute(
            f"""
            SELECT player_id, web_name, position_id, team_id, price_tenths, status, total_points
            FROM players
            WHERE snapshot_id = ? AND player_id IN ({placeholders})
            """,
            (snapshot_id, *active_player_ids),
        ).fetchall()

    player_info_map = {row[0]: row for row in player_rows}

    players_detail: list[dict[str, Any]] = []
    total_purchase_price_tenths = 0
    total_current_price_tenths = 0
    total_selling_price_tenths = 0
    team_counts: dict[str, int] = {}
    position_counts: dict[str, int] = {"GKP": 0, "DEF": 0, "MID": 0, "FWD": 0}

    # Preserve player order from active_player_ids
    for player_id in active_player_ids:
        row = player_info_map.get(player_id)
        if row is None:
            raise RuntimeError(f"Player ID {player_id} in squad was not found in FPL database snapshot.")

        _, web_name, position_id, team_id_val, current_price, status, total_points = row
        pos_abbr = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}.get(position_id, "MID")
        pos_name = Position(position_id).name
        team_short = team_map.get(team_id_val, {}).get("short_name", f"Team {team_id_val}")

        try:
            purchase_price = state.purchase_price(player_id)
        except Exception:
            purchase_price = current_price
        sell_price = selling_price(purchase_price, current_price)

        total_purchase_price_tenths += purchase_price
        total_current_price_tenths += current_price
        total_selling_price_tenths += sell_price

        team_counts[team_short] = team_counts.get(team_short, 0) + 1
        position_counts[pos_abbr] = position_counts.get(pos_abbr, 0) + 1

        p_info: dict[str, Any] = {
            "id": player_id,
            "name": web_name,
            "position": pos_name,
            "team": team_short,
            "status": status,
            "total_points": total_points,
            "purchase_price_tenths": purchase_price,
            "purchase_price_fmt": f"£{purchase_price / 10:.1f}m",
            "current_price_tenths": current_price,
            "current_price_fmt": f"£{current_price / 10:.1f}m",
            "selling_price_tenths": sell_price,
            "selling_price_fmt": f"£{sell_price / 10:.1f}m",
        }
        if player_id in actual_scores:
            p_info["gameweek_points"] = actual_scores[player_id]
        players_detail.append(p_info)

    # Validate squad rules
    all_players = store.latest_players()
    squad_players = [p for p in all_players if p.id in set(active_player_ids)]
    validation = validate_squad(squad_players, budget_tenths=None)

    total_squad_value_tenths = total_selling_price_tenths + state.bank_tenths
    gw = gameweek if gameweek is not None else (state.gameweek if state.gameweek is not None else get_current_gameweek(store))

    report = {
        "season": state.season,
        "gameweek": gw,
        "is_logged": is_logged,
        "squad_size": len(players_detail),
        "is_valid": validation.is_valid,
        "validation_errors": list(validation.errors),
        "financials": {
            "bank_tenths": state.bank_tenths,
            "bank_fmt": f"£{state.bank_tenths / 10:.1f}m",
            "squad_purchase_value_tenths": total_purchase_price_tenths,
            "squad_purchase_value_fmt": f"£{total_purchase_price_tenths / 10:.1f}m",
            "squad_current_value_tenths": total_current_price_tenths,
            "squad_current_value_fmt": f"£{total_current_price_tenths / 10:.1f}m",
            "squad_selling_value_tenths": total_selling_price_tenths,
            "squad_selling_value_fmt": f"£{total_selling_price_tenths / 10:.1f}m",
            "total_team_value_tenths": total_squad_value_tenths,
            "total_team_value_fmt": f"£{total_squad_value_tenths / 10:.1f}m",
        },
        "state": {
            "gameweek": gw,
            "free_transfers": state.free_transfers,
            "chips_remaining": list(state.chips_remaining),
        },
        "breakdown": {
            "positions": position_counts,
            "teams": team_counts,
        },
        "players": players_detail,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report
