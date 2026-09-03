import heapq
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .expected_points import project_multi_gameweek
from .fixtures import analyze_team_fixtures, get_current_gameweek
from .models import Position
from .squad_state import load_current_squad
from .storage import SnapshotStore
from .transfers import selling_price

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "fpl.sqlite3"
DEFAULT_SQUAD_PATH = PROJECT_ROOT / "config" / "current_squad.json"
TRANSFERS_REPORT_PATH = PROJECT_ROOT / "reports" / "transfer_suggestions.json"


@dataclass(frozen=True, slots=True)
class PlayerInfo:
    id: int
    name: str
    position: Position
    team_id: int
    team_short: str
    price_tenths: int
    status: str
    total_points: int
    expected_points: float = 0.0


def load_all_players_meta(
    store: SnapshotStore,
    xp_map: dict[int, float] | None = None,
) -> tuple[dict[int, PlayerInfo], dict[int, str]]:
    """Load all players and team short names from the latest snapshot with projected xP."""
    store.initialize()
    with store._connect() as connection:
        snapshot = connection.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
        if snapshot is None:
            raise RuntimeError("No FPL data found. Run `fpl update` first.")
        snapshot_id = snapshot[0]

        teams_rows = connection.execute(
            "SELECT team_id, short_name FROM teams WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchall()
        team_map = {row[0]: row[1] for row in teams_rows}

        players_rows = connection.execute(
            """
            SELECT player_id, web_name, position_id, team_id, price_tenths, status, total_points
            FROM players
            WHERE snapshot_id = ?
            """,
            (snapshot_id,),
        ).fetchall()

    players_map: dict[int, PlayerInfo] = {}
    for p_id, web_name, pos_id, t_id, price, status, pts in players_rows:
        t_short = team_map.get(t_id, f"T{t_id}")
        p_xp = xp_map.get(p_id, 0.0) if xp_map else 0.0
        players_map[p_id] = PlayerInfo(
            id=p_id,
            name=web_name,
            position=Position(pos_id),
            team_id=t_id,
            team_short=t_short,
            price_tenths=price,
            status=status,
            total_points=pts,
            expected_points=p_xp,
        )

    return players_map, team_map


def suggest_transfers(
    num_transfers: int = 1,
    squad_path: Path = DEFAULT_SQUAD_PATH,
    database_path: Path = DATABASE_PATH,
    max_results: int = 15,
    num_gameweeks: int = 5,
    report_path: Path = TRANSFERS_REPORT_PATH,
) -> dict[str, Any]:
    """Generate legal 1- to 3-transfer move recommendations for the current squad.

    Note: Evaluates up to 3 transfers. 4-transfer evaluation was found to be too slow
    due to O(N^4) combinatorial search space and is capped at max 3 for now. We may
    revisit 4+ transfer support in the future with an optimized solver (e.g. branch-and-bound or MIP).
    """
    if num_transfers not in (1, 2, 3):
        raise ValueError(
            f"Invalid num_transfers={num_transfers}. Currently only 1, 2, or 3 transfers are permitted "
            "due to combinatorial performance constraints. 4+ transfer evaluations may be revisited in future optimization."
        )

    state = load_current_squad(squad_path)
    store = SnapshotStore(database_path)
    start_gw = get_current_gameweek(store)
    target_gws = list(range(start_gw, start_gw + num_gameweeks))
    xp_map = project_multi_gameweek(target_gws, database_path=database_path)
    players_map, team_map = load_all_players_meta(store, xp_map)
    fdr_analysis = analyze_team_fixtures(database_path=database_path, num_gameweeks=num_gameweeks, start_gw=start_gw)
    fdr_map = {t["short_name"]: t["avg_difficulty"] for t in fdr_analysis["team_rankings"]}
    ticker_map = {t["short_name"]: t["ticker"] for t in fdr_analysis["team_rankings"]}

    squad_set = set(state.player_ids)
    squad_players = [players_map[p_id] for p_id in state.player_ids if p_id in players_map]

    # Calculate selling prices for current squad
    selling_prices = {
        p_id: selling_price(state.purchase_price(p_id), players_map[p_id].price_tenths)
        for p_id in state.player_ids if p_id in players_map
    }

    # Only recommend available active players
    candidate_pool = [p for p in players_map.values() if p.id not in squad_set and p.status in ("a", "d")]

    # Adjust top candidate limit per position based on number of transfers for fast execution
    cand_limit = 50 if num_transfers <= 2 else 30

    candidates_by_pos: dict[Position, list[PlayerInfo]] = {pos: [] for pos in Position}
    for p in candidate_pool:
        candidates_by_pos[p.position].append(p)

    for pos in candidates_by_pos:
        candidates_by_pos[pos].sort(
            key=lambda p: (p.expected_points, p.total_points, -fdr_map.get(p.team_short, 3.0)),
            reverse=True,
        )
        candidates_by_pos[pos] = candidates_by_pos[pos][:cand_limit]

    base_team_counts: dict[int, int] = {}
    for p in squad_players:
        base_team_counts[p.team_id] = base_team_counts.get(p.team_id, 0) + 1

    heap: list[tuple[float, float, int, int, dict[str, Any]]] = []
    entry_counter = 0
    total_evaluated = 0

    def add_result(score: float, fdr_delta: float, points_delta: int, payload: dict[str, Any]) -> None:
        nonlocal entry_counter, total_evaluated
        total_evaluated += 1
        item = (score, fdr_delta, points_delta, entry_counter, payload)
        entry_counter += 1

        if len(heap) < max_results:
            heapq.heappush(heap, item)
        elif item > heap[0]:
            heapq.heappushpop(heap, item)

    if num_transfers == 1:
        for out_p in squad_players:
            out_sell_price = selling_prices[out_p.id]
            max_budget = state.bank_tenths + out_sell_price
            out_fdr = fdr_map.get(out_p.team_short, 3.0)

            for in_p in candidates_by_pos.get(out_p.position, []):
                if in_p.price_tenths > max_budget:
                    continue

                count_in_team = base_team_counts.get(in_p.team_id, 0)
                if in_p.team_id == out_p.team_id:
                    pass
                elif count_in_team >= 3:
                    continue

                bank_after = max_budget - in_p.price_tenths
                in_fdr = fdr_map.get(in_p.team_short, 3.0)
                fdr_delta = round(out_fdr - in_fdr, 2)
                points_delta = in_p.total_points - out_p.total_points
                xp_delta = round(in_p.expected_points - out_p.expected_points, 2)
                transfer_hits = 0 if state.free_transfers >= 1 else 4
                score = round(xp_delta - transfer_hits, 2)

                add_result(score, fdr_delta, points_delta, {
                    "type": "1-transfer",
                    "outgoing": [{
                        "id": out_p.id,
                        "name": out_p.name,
                        "position": out_p.position.name,
                        "team": out_p.team_short,
                        "selling_price_fmt": f"£{out_sell_price / 10:.1f}m",
                        "fdr": out_fdr,
                        "xp": out_p.expected_points,
                    }],
                    "incoming": [{
                        "id": in_p.id,
                        "name": in_p.name,
                        "position": in_p.position.name,
                        "team": in_p.team_short,
                        "price_fmt": f"£{in_p.price_tenths / 10:.1f}m",
                        "fdr": in_fdr,
                        "ticker": ticker_map.get(in_p.team_short, ""),
                        "xp": in_p.expected_points,
                    }],
                    "bank_after_fmt": f"£{bank_after / 10:.1f}m",
                    "bank_after_tenths": bank_after,
                    "xp_delta": xp_delta,
                    "fdr_improvement": fdr_delta,
                    "points_delta": points_delta,
                    "transfer_hits": transfer_hits,
                    "score": score,
                })

    elif num_transfers == 2:
        squad_list = list(squad_players)
        transfer_hits = max(0, 2 - state.free_transfers) * 4

        for i in range(len(squad_list)):
            for j in range(i + 1, len(squad_list)):
                out1, out2 = squad_list[i], squad_list[j]
                out_sell_sum = selling_prices[out1.id] + selling_prices[out2.id]
                max_budget = state.bank_tenths + out_sell_sum

                temp_team_counts = dict(base_team_counts)
                temp_team_counts[out1.team_id] -= 1
                temp_team_counts[out2.team_id] -= 1

                pos1_cands = candidates_by_pos.get(out1.position, [])
                pos2_cands = candidates_by_pos.get(out2.position, [])
                min_p2_price = min((p.price_tenths for p in pos2_cands), default=0)

                for in1 in pos1_cands:
                    if in1.price_tenths + min_p2_price > max_budget:
                        continue
                    if temp_team_counts.get(in1.team_id, 0) >= 3:
                        continue

                    temp_team_counts[in1.team_id] = temp_team_counts.get(in1.team_id, 0) + 1

                    for in2 in pos2_cands:
                        if in1.id == in2.id:
                            continue
                        if in1.price_tenths + in2.price_tenths > max_budget:
                            continue
                        if temp_team_counts.get(in2.team_id, 0) >= 3:
                            continue

                        bank_after = max_budget - (in1.price_tenths + in2.price_tenths)
                        out_fdr_avg = (fdr_map.get(out1.team_short, 3.0) + fdr_map.get(out2.team_short, 3.0)) / 2
                        in_fdr_avg = (fdr_map.get(in1.team_short, 3.0) + fdr_map.get(in2.team_short, 3.0)) / 2
                        fdr_delta = round(out_fdr_avg - in_fdr_avg, 2)
                        points_delta = (in1.total_points + in2.total_points) - (out1.total_points + out2.total_points)
                        out_xp = round(out1.expected_points + out2.expected_points, 2)
                        in_xp = round(in1.expected_points + in2.expected_points, 2)
                        xp_delta = round(in_xp - out_xp, 2)
                        score = round(xp_delta - transfer_hits, 2)

                        add_result(score, fdr_delta, points_delta, {
                            "type": "2-transfer",
                            "outgoing": [
                                {"id": out1.id, "name": out1.name, "position": out1.position.name, "team": out1.team_short, "selling_price_fmt": f"£{selling_prices[out1.id] / 10:.1f}m", "xp": out1.expected_points},
                                {"id": out2.id, "name": out2.name, "position": out2.position.name, "team": out2.team_short, "selling_price_fmt": f"£{selling_prices[out2.id] / 10:.1f}m", "xp": out2.expected_points},
                            ],
                            "incoming": [
                                {"id": in1.id, "name": in1.name, "position": in1.position.name, "team": in1.team_short, "price_fmt": f"£{in1.price_tenths / 10:.1f}m", "ticker": ticker_map.get(in1.team_short, ""), "xp": in1.expected_points},
                                {"id": in2.id, "name": in2.name, "position": in2.position.name, "team": in2.team_short, "price_fmt": f"£{in2.price_tenths / 10:.1f}m", "ticker": ticker_map.get(in2.team_short, ""), "xp": in2.expected_points},
                            ],
                            "bank_after_fmt": f"£{bank_after / 10:.1f}m",
                            "bank_after_tenths": bank_after,
                            "xp_delta": xp_delta,
                            "fdr_improvement": fdr_delta,
                            "points_delta": points_delta,
                            "transfer_hits": transfer_hits,
                            "score": score,
                        })

                    temp_team_counts[in1.team_id] -= 1

    elif num_transfers == 3:
        squad_list = list(squad_players)
        transfer_hits = max(0, 3 - state.free_transfers) * 4

        for i in range(len(squad_list)):
            for j in range(i + 1, len(squad_list)):
                for k in range(j + 1, len(squad_list)):
                    out1, out2, out3 = squad_list[i], squad_list[j], squad_list[k]
                    out_sell_sum = selling_prices[out1.id] + selling_prices[out2.id] + selling_prices[out3.id]
                    max_budget = state.bank_tenths + out_sell_sum

                    temp_team_counts = dict(base_team_counts)
                    temp_team_counts[out1.team_id] -= 1
                    temp_team_counts[out2.team_id] -= 1
                    temp_team_counts[out3.team_id] -= 1

                    pos1_cands = candidates_by_pos.get(out1.position, [])
                    pos2_cands = candidates_by_pos.get(out2.position, [])
                    pos3_cands = candidates_by_pos.get(out3.position, [])

                    min_p2_price = min((p.price_tenths for p in pos2_cands), default=0)
                    min_p3_price = min((p.price_tenths for p in pos3_cands), default=0)

                    for in1 in pos1_cands:
                        if in1.price_tenths + min_p2_price + min_p3_price > max_budget:
                            continue
                        if temp_team_counts.get(in1.team_id, 0) >= 3:
                            continue

                        temp_team_counts[in1.team_id] = temp_team_counts.get(in1.team_id, 0) + 1

                        for in2 in pos2_cands:
                            if in1.id == in2.id:
                                continue
                            if in1.price_tenths + in2.price_tenths + min_p3_price > max_budget:
                                continue
                            if temp_team_counts.get(in2.team_id, 0) >= 3:
                                continue

                            temp_team_counts[in2.team_id] = temp_team_counts.get(in2.team_id, 0) + 1

                            for in3 in pos3_cands:
                                if in3.id in (in1.id, in2.id):
                                    continue
                                total_cost = in1.price_tenths + in2.price_tenths + in3.price_tenths
                                if total_cost > max_budget:
                                    continue
                                if temp_team_counts.get(in3.team_id, 0) >= 3:
                                    continue

                                bank_after = max_budget - total_cost
                                out_fdr_avg = (fdr_map.get(out1.team_short, 3.0) + fdr_map.get(out2.team_short, 3.0) + fdr_map.get(out3.team_short, 3.0)) / 3
                                in_fdr_avg = (fdr_map.get(in1.team_short, 3.0) + fdr_map.get(in2.team_short, 3.0) + fdr_map.get(in3.team_short, 3.0)) / 3
                                fdr_delta = round(out_fdr_avg - in_fdr_avg, 2)
                                points_delta = (in1.total_points + in2.total_points + in3.total_points) - (out1.total_points + out2.total_points + out3.total_points)
                                out_xp = round(out1.expected_points + out2.expected_points + out3.expected_points, 2)
                                in_xp = round(in1.expected_points + in2.expected_points + in3.expected_points, 2)
                                xp_delta = round(in_xp - out_xp, 2)
                                score = round(xp_delta - transfer_hits, 2)

                                add_result(score, fdr_delta, points_delta, {
                                    "type": "3-transfer",
                                    "outgoing": [
                                        {"id": out1.id, "name": out1.name, "position": out1.position.name, "team": out1.team_short, "selling_price_fmt": f"£{selling_prices[out1.id] / 10:.1f}m", "xp": out1.expected_points},
                                        {"id": out2.id, "name": out2.name, "position": out2.position.name, "team": out2.team_short, "selling_price_fmt": f"£{selling_prices[out2.id] / 10:.1f}m", "xp": out2.expected_points},
                                        {"id": out3.id, "name": out3.name, "position": out3.position.name, "team": out3.team_short, "selling_price_fmt": f"£{selling_prices[out3.id] / 10:.1f}m", "xp": out3.expected_points},
                                    ],
                                    "incoming": [
                                        {"id": in1.id, "name": in1.name, "position": in1.position.name, "team": in1.team_short, "price_fmt": f"£{in1.price_tenths / 10:.1f}m", "ticker": ticker_map.get(in1.team_short, ""), "xp": in1.expected_points},
                                        {"id": in2.id, "name": in2.name, "position": in2.position.name, "team": in2.team_short, "price_fmt": f"£{in2.price_tenths / 10:.1f}m", "ticker": ticker_map.get(in2.team_short, ""), "xp": in2.expected_points},
                                        {"id": in3.id, "name": in3.name, "position": in3.position.name, "team": in3.team_short, "price_fmt": f"£{in3.price_tenths / 10:.1f}m", "ticker": ticker_map.get(in3.team_short, ""), "xp": in3.expected_points},
                                    ],
                                    "bank_after_fmt": f"£{bank_after / 10:.1f}m",
                                    "bank_after_tenths": bank_after,
                                    "xp_delta": xp_delta,
                                    "fdr_improvement": fdr_delta,
                                    "points_delta": points_delta,
                                    "transfer_hits": transfer_hits,
                                    "score": score,
                                })

                            temp_team_counts[in2.team_id] -= 1

                        temp_team_counts[in1.team_id] -= 1

    # Note: 4-transfer evaluations (O(N^4)) were removed because combinatorial brute-force
    # search across squad and candidate pools is too slow in practice.
    # Transfers are capped at max 3 for now. In a future milestone (e.g. V0.3), we may want
    # to revisit 4+ transfer moves using a dedicated optimizer (such as integer linear programming
    # or pruned branch-and-bound search).

    sorted_heap = sorted(heap, reverse=True)
    top_results = [item[4] for item in sorted_heap]

    report = {
        "num_transfers": num_transfers,
        "free_transfers_available": state.free_transfers,
        "target_gameweeks": target_gws,
        "evaluation_horizon_gws": num_gameweeks,
        "total_options_evaluated": total_evaluated,
        "top_suggestions": top_results,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return report



