"""Direct domain regressions for conserved money and prevalidated live commands."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from fpl_manager.decision_log import (
    apply_wildcard_or_freehit, get_gameweek_decision, log_decision_from_current_squad,
    reconcile_squad_transfers, record_gameweek_decision, undo_gameweek_changes,
)
from fpl_manager.squad_state import CurrentSquadState, load_current_squad, save_current_squad
from fpl_manager.storage import SnapshotStore, utc_timestamp
from fpl_manager.teams import advance_current_squad, get_team, get_team_squad_path, list_teams
from fpl_manager.transfers import Transfer, execute_transfers, prepare_transfer_finance, selling_price


STARTERS = [1, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14]
BENCH = [2, 6, 7, 15]


@pytest.fixture
def finance_env(tmp_path):
    database = tmp_path / "finance.sqlite3"
    config = tmp_path / "config"
    squad = config / "teams" / "alpha" / "squad.json"
    elements = []
    for pid in range(1, 17):
        elements.append({
            "id": pid, "web_name": f"P{pid}",
            "element_type": 1 if pid <= 2 else 2 if pid <= 7 else 3 if pid <= 12 else 4,
            "team": (pid - 1) % 6 + 1, "now_cost": 60 if pid == 16 else 50,
            "status": "a", "total_points": 20,
        })
    store = SnapshotStore(database)
    store.save_snapshot({
        "teams": [{"id": i, "name": f"T{i}", "short_name": f"T{i}"} for i in range(1, 7)],
        "elements": elements,
    }, [{"id": 1, "event": 2, "team_h": 1, "team_a": 2,
         "finished": False, "team_h_difficulty": 3, "team_a_difficulty": 3}], utc_timestamp())
    state = CurrentSquadState(
        tuple(range(1, 16)), {i: 50 for i in range(1, 16)}, 0, 1,
        ("wildcard_1", "free_hit", "bench_boost", "triple_captain"), "2026/27", 2, 1,
    )
    save_current_squad(squad, state)
    return database, squad, store


@pytest.mark.parametrize("purchase,current,expected", [(65, 60, 60), (60, 61, 60), (60, 62, 61), (60, 63, 61)])
def test_sale_price_falls_and_integer_rises(purchase, current, expected):
    assert selling_price(purchase, current) == expected


def test_unaffordable_manual_decision_has_no_effect(finance_env):
    database, squad, _ = finance_env
    before = squad.read_bytes()
    with pytest.raises(ValueError, match="need"):
        log_decision_from_current_squad(
            gameweek=2, squad_path=squad, database_path=database, team_id="alpha",
            transfers=["15:16"],
        )
    assert squad.read_bytes() == before
    assert get_gameweek_decision(2, team_id="alpha", database_path=database) is None


def test_transfer_capture_uses_each_teams_exact_state(finance_env, monkeypatch):
    database, alpha, _ = finance_env
    captured = []

    def suggestions(**kwargs):
        captured.append(kwargs)
        return {"top_suggestions": []}

    monkeypatch.setattr("fpl_manager.suggest_transfers.suggest_transfers", suggestions)
    original = load_current_squad(alpha)
    beta = alpha.parent.parent / "beta" / "squad.json"
    ids = tuple(16 if pid == 15 else pid for pid in original.player_ids)
    save_current_squad(beta, replace(
        original, player_ids=ids, bank_tenths=23,
        purchase_prices_tenths={pid: 60 if pid == 16 else 50 for pid in ids},
    ))
    for team_id, path in (("alpha", alpha), ("beta", beta)):
        log_decision_from_current_squad(
            gameweek=2, squad_path=path, database_path=database, team_id=team_id,
        )
    assert [item["team_id"] for item in captured] == ["alpha", "beta"]
    assert captured[0]["state"].bank_tenths == 0
    assert captured[1]["state"].bank_tenths == 23
    assert 15 in captured[0]["state"].player_ids
    assert 16 in captured[1]["state"].player_ids
    assert all(item["gameweek"] == 2 and item["report_path"] is None for item in captured)
    assert all("squad_path" not in item for item in captured)


def test_combined_cli_decision_and_score_failure_rolls_back_both_stores(finance_env, monkeypatch):
    from fpl_manager.cli import main
    from fpl_manager import cli

    database, squad, _ = finance_env
    before = squad.read_bytes()
    monkeypatch.setattr(cli, "DATABASE_PATH", database)

    def reject_score(*args, **kwargs):
        raise ValueError("injected score rejection")

    monkeypatch.setattr("fpl_manager.decision_log.record_actual_gameweek_score", reject_score)
    with pytest.raises(SystemExit):
        main([
            "log-decision", "--squad", str(squad), "--team", "alpha",
            "--gameweek", "2", "--actual-points", "50",
        ])
    assert squad.read_bytes() == before
    assert get_gameweek_decision(2, team_id="alpha", database_path=database) is None


@pytest.mark.parametrize("operation", ["decision", "transfer", "strategic"])
def test_later_deadline_mutations_use_atomic_chip_renewal(finance_env, operation):
    database, squad, _ = finance_env
    state = replace(
        load_current_squad(squad), gameweek=19, chip_segment=1,
        chips_remaining=(), bank_tenths=10,
    )
    save_current_squad(squad, state)
    if operation == "decision":
        log_decision_from_current_squad(gameweek=20, squad_path=squad, database_path=database, team_id="alpha")
    elif operation == "transfer":
        execute_transfers(
            squad, [Transfer(15, 16)], database_path=database, gameweek=20, team_id="alpha",
        )
    else:
        apply_wildcard_or_freehit(
            squad, 20, "wildcard", list(state.player_ids), STARTERS, BENCH,
            13, 8, 10, team_id="alpha", database_path=database,
        )
    updated = load_current_squad(squad)
    assert updated.gameweek == 20 and updated.chip_segment == 2
    assert {"free_hit", "bench_boost", "triple_captain"} <= set(updated.chips_remaining)
    if operation != "strategic":
        assert "wildcard_2" in updated.chips_remaining


def test_finance_operation_and_reconciliation_use_sale_loss(finance_env):
    _, squad, store = finance_env
    state = replace(load_current_squad(squad), bank_tenths=10,
                    purchase_prices_tenths={i: 65 if i == 15 else 50 for i in range(1, 16)})
    updated, records = prepare_transfer_finance(state, store.latest_players(), [Transfer(15, 16)])
    assert updated.bank_tenths == 0
    assert records[0]["selling_price_tenths"] == 50
    assert updated.purchase_price(16) == 60
    assert reconcile_squad_transfers(state.player_ids, updated.player_ids, store, state.purchase_prices_tenths)[0]["selling_price_tenths"] == 50


def test_wildcard_invalid_captain_does_not_consume_or_write(finance_env):
    database, squad, _ = finance_env
    before = squad.read_bytes()
    with pytest.raises(ValueError, match="cannot be the same"):
        apply_wildcard_or_freehit(
            squad, 2, "wildcard", list(range(1, 16)), STARTERS, BENCH,
            13, 13, 0, team_id="alpha", database_path=database,
        )
    assert squad.read_bytes() == before
    assert get_gameweek_decision(2, team_id="alpha", database_path=database) is None


def test_unavailable_chip_replacement_preserves_decision_and_inventory(finance_env):
    database, squad, store = finance_env
    state = load_current_squad(squad)
    save_current_squad(squad, replace(state, chips_remaining=("wildcard_1", "bench_boost", "triple_captain")))
    log_decision_from_current_squad(
        gameweek=2, squad_path=squad, team_id="alpha", database_path=database,
        chip_played="wildcard", transfer_hits=8,
    )
    before_squad = squad.read_bytes()
    before_decision = get_gameweek_decision(2, team_id="alpha", database_path=database)
    with store._connect() as connection:
        before_recommendations = connection.execute("SELECT * FROM decision_recommendations").fetchall()
    with pytest.raises(ValueError, match="free_hit.*not available"):
        log_decision_from_current_squad(
            gameweek=2, squad_path=squad, team_id="alpha", database_path=database,
            chip_played="free_hit", transfer_hits=10, overwrite=True,
        )
    assert squad.read_bytes() == before_squad
    assert get_gameweek_decision(2, team_id="alpha", database_path=database) == before_decision
    with store._connect() as connection:
        assert connection.execute("SELECT * FROM decision_recommendations").fetchall() == before_recommendations


def test_log_write_failure_rolls_back_sql(finance_env, monkeypatch):
    database, squad, _ = finance_env
    before = squad.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("injected write failure")
    monkeypatch.setattr("fpl_manager.decision_log.save_current_squad", fail)
    with pytest.raises(OSError, match="injected"):
        log_decision_from_current_squad(gameweek=2, squad_path=squad, team_id="alpha", database_path=database)
    assert squad.read_bytes() == before
    assert get_gameweek_decision(2, team_id="alpha", database_path=database) is None


def test_undo_write_failure_preserves_decision(finance_env, monkeypatch):
    database, squad, _ = finance_env
    for gw in (1, 2):
        record_gameweek_decision(
            gw, list(range(1, 16)), STARTERS, BENCH, 13, 8,
            team_id="alpha", database_path=database, capture_recommendations=False,
        )
    before = squad.read_bytes()
    def fail(*args, **kwargs):
        raise OSError("injected write failure")
    monkeypatch.setattr("fpl_manager.decision_log.save_current_squad", fail)
    with pytest.raises(OSError, match="injected"):
        undo_gameweek_changes(squad, 2, team_id="alpha", database_path=database)
    assert squad.read_bytes() == before
    assert get_gameweek_decision(2, team_id="alpha", database_path=database) is not None


def test_read_queries_and_explicit_chip_renewal(finance_env):
    database, squad, _ = finance_env
    save_current_squad(squad, replace(load_current_squad(squad), gameweek=19, chips_remaining=()))
    config = squad.parents[2]
    before = {str(path): path.read_bytes() for path in config.rglob("*") if path.is_file()}
    assert get_team_squad_path("alpha", config) == squad
    list_teams(config, database)
    get_team("alpha", config, database)
    assert {str(path): path.read_bytes() for path in config.rglob("*") if path.is_file()} == before
    advance_current_squad(squad, 20, team_id="alpha", config_dir=config, database_path=database)
    renewed = load_current_squad(squad)
    assert renewed.chip_segment == 2
    assert set(renewed.chips_remaining) == {"wildcard_2", "free_hit", "bench_boost", "triple_captain"}
    save_current_squad(squad, replace(renewed, chips_remaining=("wildcard_2",)))
    advance_current_squad(squad, 20, team_id="alpha", config_dir=config, database_path=database)
    assert load_current_squad(squad).chips_remaining == ("wildcard_2",)


def test_legacy_advanced_chip_inventory_is_not_invented(finance_env):
    database, squad, _ = finance_env
    save_current_squad(squad, replace(load_current_squad(squad), gameweek=20, chip_segment=None, chips_remaining=()))
    before = squad.read_bytes()
    with pytest.raises(ValueError, match="ambiguous"):
        advance_current_squad(squad, 21, team_id="alpha", database_path=database)
    assert squad.read_bytes() == before


def test_repeated_lineup_save_does_not_charge_again(finance_env):
    database, squad, _ = finance_env
    save_current_squad(squad, replace(load_current_squad(squad), bank_tenths=10))
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2)
    bank = load_current_squad(squad).bank_tenths
    log_decision_from_current_squad(gameweek=2, squad_path=squad, team_id="alpha", database_path=database)
    log_decision_from_current_squad(
        gameweek=2, squad_path=squad, team_id="alpha", database_path=database, transfers=["15:16"],
    )
    log_decision_from_current_squad(gameweek=2, squad_path=squad, team_id="alpha", database_path=database)
    assert load_current_squad(squad).bank_tenths == bank == 0


def test_appreciated_squad_above_initial_budget_is_legal(finance_env):
    _, squad, store = finance_env
    state = replace(load_current_squad(squad), bank_tenths=500)
    updated, _ = prepare_transfer_finance(state, store.latest_players(), [Transfer(15, 16)])
    assert sum(updated.purchase_prices_tenths.values()) + updated.bank_tenths > 1000


def test_capture_isolates_two_explicit_team_contexts(finance_env, monkeypatch):
    database, squad, store = finance_env
    other = squad.parent.parent / "beta" / "squad.json"
    original = load_current_squad(squad)
    prices = {pid: price for pid, price in original.purchase_prices_tenths.items() if pid != 15}
    prices[16] = 60
    save_current_squad(other, replace(original, player_ids=tuple(range(1, 15)) + (16,),
                                     purchase_prices_tenths=prices, bank_tenths=7, gameweek=3))
    observed = []
    def pure_lineup(*, database_path, gameweek, state, report_path):
        assert report_path is None
        observed.append((gameweek, state.bank_tenths, state.player_ids))
        return {"gameweek": gameweek, "all_squad": list(state.player_ids)}
    monkeypatch.setattr("fpl_manager.lineup.select_starting_lineup", pure_lineup)
    log_decision_from_current_squad(squad_path=squad, team_id="alpha", database_path=database)
    log_decision_from_current_squad(squad_path=other, team_id="beta", database_path=database)
    assert observed == [(2, 0, original.player_ids), (3, 7, tuple(range(1, 15)) + (16,))]
    with store._connect() as connection:
        rows = connection.execute(
            "SELECT d.team_id, r.recommended_lineup_json FROM decisions d "
            "JOIN decision_recommendations r ON r.decision_id = d.id ORDER BY d.team_id"
        ).fetchall()
    captured = {team: json.loads(text) for team, text in rows}
    assert captured["alpha"]["decision_context"]["team_id"] == "alpha"
    assert captured["beta"]["decision_context"]["team_id"] == "beta"
    assert 15 in captured["alpha"]["all_squad"] and 15 not in captured["beta"]["all_squad"]


def test_past_logging_preserves_current_ownership_and_marks_capture_unavailable(finance_env):
    database, squad, store = finance_env
    save_current_squad(squad, replace(load_current_squad(squad), gameweek=3))
    before = squad.read_bytes()
    result = log_decision_from_current_squad(
        gameweek=1, squad_path=squad, team_id="alpha", database_path=database,
        starting_player_ids=STARTERS, bench_player_ids=BENCH,
    )
    assert result["current_squad_updated"] is False
    assert result["prediction_status"] == "not_captured_point_in_time_unavailable"
    assert squad.read_bytes() == before
    with store._connect() as connection:
        text = connection.execute("SELECT recommended_lineup_json FROM decision_recommendations").fetchone()[0]
    assert json.loads(text)["reason"] == "point_in_time_snapshot_unavailable"


def test_empty_read_does_not_initialize_team_files(tmp_path):
    config = tmp_path / "nonexistent_config"
    assert list_teams(config) == []
    assert get_team_squad_path("default", config) == config / "teams" / "default" / "squad.json"
    assert not config.exists()


def test_advance_command_accepts_current_deadline_default(finance_env):
    database, squad, _ = finance_env
    result = advance_current_squad(squad, team_id="alpha", database_path=database)
    assert result["gameweek"] == 2
    assert result["chip_segment"] == 1


def test_pure_lineup_and_squad_report_do_not_fetch_actuals_or_write(finance_env, monkeypatch):
    from fpl_manager.lineup import select_starting_lineup
    from fpl_manager.squad_report import generate_squad_report
    database, squad, _ = finance_env
    calls = []
    def unexpected(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Pure calculations cannot fetch match outcomes.")
    monkeypatch.setattr("fpl_manager.scores.get_or_fetch_gameweek_scores", unexpected)
    state = load_current_squad(squad)
    before = squad.read_bytes()
    assert select_starting_lineup(
        squad_path=Path("never_read.json"), state=state, database_path=database, gameweek=2, report_path=None,
    )["gameweek"] == 2
    assert generate_squad_report(
        squad_path=Path("never_read.json"), state=state, database_path=database, gameweek=2, report_path=None,
    )["gameweek"] == 2
    assert squad.read_bytes() == before
    assert not calls


def test_offline_execution_policy_is_explicit_and_scoped(tmp_path, monkeypatch):
    from fpl_manager.backtest import engine
    from fpl_manager.backtest.strategies import NoTransferStrategy
    from fpl_manager.execution import resolve_execution_version
    from fpl_manager.historical.ingestion import generate_mock_season
    season = tmp_path / "mock_season"
    generate_mock_season(season, season="2023-24", num_gameweeks=2, num_teams=6, players_per_team=5)
    original = engine.build_historical_snapshot
    observed = []
    def snapshot(*args, **kwargs):
        observed.append(resolve_execution_version().value)
        return original(*args, **kwargs)
    monkeypatch.setattr(engine, "build_historical_snapshot", snapshot)
    legacy = engine.run_sequential_simulation(season, NoTransferStrategy(), end_gw=1)
    assert legacy.execution_version == "v146" and set(observed) == {"v146"}
    observed.clear()
    corrected = engine.run_sequential_simulation(season, NoTransferStrategy(), end_gw=1, execution_version="v147")
    assert corrected.execution_version == "v147" and set(observed) == {"v147"}
    assert resolve_execution_version().value == "v147"
    assert corrected.configuration_hash != legacy.configuration_hash


def _appreciated_state(finance_env, gameweek=2):
    _, squad, store = finance_env
    with store._connect() as connection, connection:
        connection.execute("UPDATE players SET price_tenths = 70 WHERE player_id = 15")
        connection.execute("UPDATE players SET price_tenths = 50 WHERE player_id = 16")
    state = replace(
        load_current_squad(squad), bank_tenths=100, gameweek=gameweek,
        purchase_prices_tenths={pid: 65 if pid == 15 else 50 for pid in range(1, 16)},
    )
    save_current_squad(squad, state)
    return state


@pytest.mark.parametrize("entry", ["strategic", "execute", "manual"])
@pytest.mark.parametrize("source_gw,target_gw", [(2, 3), (2, 5), (19, 20)])
def test_free_hit_restores_authoritative_ownership_after_restart(finance_env, entry, source_gw, target_gw):
    database, squad, _ = finance_env
    original = _appreciated_state(finance_env, source_gw)
    if entry == "strategic":
        apply_wildcard_or_freehit(
            squad, source_gw, "freehit", list(range(1, 15)) + [16],
            STARTERS, [2, 6, 7, 16], 13, 8, 0, team_id="alpha", database_path=database,
        )
    elif entry == "execute":
        execute_transfers(squad, [(15, 16)], database_path=database, gameweek=source_gw,
                          chip_played="FH", team_id="alpha")
    else:
        log_decision_from_current_squad(
            gameweek=source_gw, squad_path=squad, database_path=database, team_id="alpha",
            transfers=["15:16"], chip_played="FH",
        )
    temporary = load_current_squad(squad)
    assert temporary.bank_tenths == 117 and 16 in temporary.player_ids
    assert temporary.pre_free_hit_state.purchase_prices_tenths[15] == 65
    for _ in range(2):
        log_decision_from_current_squad(
            gameweek=source_gw, squad_path=squad, database_path=database, team_id="alpha",
        )
    # Loading through a new bus/state reader models a service restart.
    advance_current_squad(squad, target_gw, team_id="alpha", database_path=database)
    restored = load_current_squad(squad)
    assert restored.player_ids == original.player_ids
    assert restored.purchase_prices_tenths == original.purchase_prices_tenths
    assert restored.bank_tenths == 100 and restored.pre_free_hit_state is None
    assert restored.free_transfers == 1
    if target_gw < 20:
        assert "free_hit" not in restored.chips_remaining
    else:
        assert restored.chip_segment == 2 and "free_hit" in restored.chips_remaining
    assert get_gameweek_decision(source_gw, team_id="alpha", database_path=database)["chip_played"] is not None


def test_free_hit_later_transfer_and_undo_preserve_first_snapshot(finance_env):
    database, squad, _ = finance_env
    original = _appreciated_state(finance_env)
    record_gameweek_decision(1, list(original.player_ids), STARTERS, BENCH, 13, 8,
                            team_id="alpha", database_path=database, capture_recommendations=False)
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2,
                      chip_played="FH", team_id="alpha")
    execute_transfers(squad, [(16, 15)], database_path=database, gameweek=2, team_id="alpha")
    assert load_current_squad(squad).pre_free_hit_state.bank_tenths == 100
    undo_gameweek_changes(squad, 2, team_id="alpha", database_path=database)
    reverted = load_current_squad(squad)
    assert reverted.purchase_price(15) == 65 and reverted.bank_tenths == 100
    assert reverted.pre_free_hit_state is None and "free_hit" in reverted.chips_remaining


@pytest.mark.parametrize("activation", ["manual", "strategic", "execute"])
def test_late_free_hit_activation_reverts_all_same_deadline_transfers(finance_env, activation):
    database, squad, _ = finance_env
    original = _appreciated_state(finance_env)
    execute_transfers(squad, [(15, 16)], gameweek=2, team_id="alpha", database_path=database)
    traded = load_current_squad(squad)
    if activation == "manual":
        log_decision_from_current_squad(
            gameweek=2, squad_path=squad, team_id="alpha", database_path=database, chip_played="FH",
        )
    elif activation == "strategic":
        apply_wildcard_or_freehit(
            squad, 2, "freehit", list(traded.player_ids), STARTERS, [2, 6, 7, 16],
            13, 8, 0, team_id="alpha", database_path=database,
        )
    else:
        execute_transfers(
            squad, [(16, 15)], gameweek=2, team_id="alpha", database_path=database, chip_played="FH",
        )
    temporary = load_current_squad(squad)
    assert temporary.pre_free_hit_state.player_ids == original.player_ids
    assert temporary.pre_free_hit_state.purchase_prices_tenths == original.purchase_prices_tenths
    assert temporary.pre_free_hit_state.bank_tenths == original.bank_tenths
    advance_current_squad(squad, 3, team_id="alpha", database_path=database)
    restored = load_current_squad(squad)
    assert restored.player_ids == original.player_ids
    assert restored.purchase_prices_tenths == original.purchase_prices_tenths
    assert restored.bank_tenths == original.bank_tenths


@pytest.mark.parametrize("price", [60, 70])
def test_undo_recovers_legacy_human_acquisition_not_selling_quote(finance_env, price):
    database, squad, store = finance_env
    original = _appreciated_state(finance_env)
    with store._connect() as connection, connection:
        connection.execute("UPDATE players SET price_tenths = ? WHERE player_id = 15", (price,))
    record_gameweek_decision(
        1, list(original.player_ids), STARTERS, BENCH, 13, 8, team_id="alpha",
        transfers=[{"outgoing_id": 16, "incoming_id": 15, "purchase_price_tenths": 65}],
        database_path=database, capture_recommendations=False,
    )
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2, team_id="alpha")
    raw = json.loads(squad.read_text(encoding="utf-8"))
    raw.pop("gameweek_start_state", None)
    squad.write_text(json.dumps(raw), encoding="utf-8")
    with store._connect() as connection, connection:
        row = connection.execute("SELECT id, transfers_json FROM decisions WHERE gameweek=2").fetchone()
        txs = json.loads(row[1])
        txs[0].pop("outgoing_purchase_price_tenths")
        connection.execute("UPDATE decisions SET transfers_json=? WHERE id=?", (json.dumps(txs), row[0]))
    undo_gameweek_changes(squad, 2, team_id="alpha", database_path=database)
    assert load_current_squad(squad).purchase_price(15) == 65
    assert load_current_squad(squad).bank_tenths == 100


def test_undo_unverified_legacy_basis_rejects_without_effect(finance_env):
    database, squad, store = finance_env
    original = _appreciated_state(finance_env)
    record_gameweek_decision(1, list(original.player_ids), STARTERS, BENCH, 13, 8,
                            team_id="alpha", database_path=database, capture_recommendations=False)
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2, team_id="alpha")
    raw = json.loads(squad.read_text(encoding="utf-8"))
    raw.pop("gameweek_start_state", None)
    squad.write_text(json.dumps(raw), encoding="utf-8")
    # A mutable legacy/default portfolio is not this team's acquisition record.
    save_current_squad(squad.parent.parent / "current_squad.json", replace(original, bank_tenths=999))
    with store._connect() as connection, connection:
        row = connection.execute("SELECT id, transfers_json FROM decisions WHERE gameweek=2").fetchone()
        txs = json.loads(row[1])
        txs[0].pop("outgoing_purchase_price_tenths")
        connection.execute("UPDATE decisions SET transfers_json=? WHERE id=?", (json.dumps(txs), row[0]))
        before_recs = connection.execute("SELECT * FROM decision_recommendations").fetchall()
    before = squad.read_bytes()
    decision = get_gameweek_decision(2, team_id="alpha", database_path=database)
    with pytest.raises(ValueError, match="authoritative.*purchase|purchase.*basis"):
        undo_gameweek_changes(squad, 2, team_id="alpha", database_path=database)
    assert squad.read_bytes() == before
    assert get_gameweek_decision(2, team_id="alpha", database_path=database) == decision
    with store._connect() as connection:
        assert connection.execute("SELECT * FROM decision_recommendations").fetchall() == before_recs


def test_legacy_free_hit_without_snapshot_cannot_advance(finance_env):
    database, squad, _ = finance_env
    original = _appreciated_state(finance_env)
    record_gameweek_decision(2, list(original.player_ids), STARTERS, BENCH, 13, 8,
                            chip_played="FH", team_id="alpha", database_path=database,
                            capture_recommendations=False)
    before = squad.read_bytes()
    with pytest.raises(ValueError, match="Free Hit.*authoritative|Free Hit.*snapshot"):
        advance_current_squad(squad, 3, team_id="alpha", database_path=database)
    assert squad.read_bytes() == before


def test_free_hit_clone_keeps_isolated_restoration_state(finance_env):
    from fpl_manager.teams import create_team
    database, squad, _ = finance_env
    original = _appreciated_state(finance_env)
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2,
                      chip_played="FH", team_id="alpha")
    clone = create_team("Clone", copy_from_team_id="alpha", config_dir=squad.parents[2],
                        database_path=database, set_as_active=False)
    cloned_path = Path(clone["squad_path"])
    advance_current_squad(cloned_path, 3, team_id="clone", database_path=database)
    assert load_current_squad(cloned_path).player_ids == original.player_ids
    assert load_current_squad(cloned_path).bank_tenths == 100
    assert load_current_squad(cloned_path).purchase_price(15) == 65
    assert load_current_squad(squad).bank_tenths == 117


def test_free_hit_undo_without_previous_decision_uses_saved_human_state(finance_env):
    database, squad, _ = finance_env
    original = _appreciated_state(finance_env)
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2,
                      chip_played="FH", team_id="alpha")
    undo_gameweek_changes(squad, 2, team_id="alpha", database_path=database)
    reverted = load_current_squad(squad)
    assert reverted.player_ids == original.player_ids and reverted.bank_tenths == 100
    assert reverted.purchase_price(15) == 65 and reverted.pre_free_hit_state is None


def test_snapshot_backed_undo_preserves_free_transfers_without_sql_history(finance_env):
    database, squad, _ = finance_env
    original = replace(_appreciated_state(finance_env, gameweek=10), free_transfers=4)
    save_current_squad(squad, original)
    execute_transfers(
        squad, [(15, 16)], database_path=database, gameweek=10, chip_played="FH", team_id="alpha",
    )
    assert load_current_squad(squad).gameweek_start_state.free_transfers == 4
    undo_gameweek_changes(squad, 10, team_id="alpha", database_path=database)
    restored = load_current_squad(squad)
    assert restored.free_transfers == 4
    assert restored.player_ids == original.player_ids
    assert restored.purchase_prices_tenths == original.purchase_prices_tenths
    assert restored.bank_tenths == original.bank_tenths


def test_undo_sale_reacquisition_preserves_original_basis_and_integer_cash(finance_env):
    database, squad, _ = finance_env
    original = _appreciated_state(finance_env)
    record_gameweek_decision(1, list(original.player_ids), STARTERS, BENCH, 13, 8,
                            team_id="alpha", database_path=database, capture_recommendations=False)
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2, team_id="alpha")
    execute_transfers(squad, [(16, 15)], database_path=database, gameweek=2, team_id="alpha")
    assert load_current_squad(squad).purchase_price(15) == 70
    assert load_current_squad(squad).bank_tenths == 97
    undo_gameweek_changes(squad, 2, team_id="alpha", database_path=database)
    assert load_current_squad(squad).purchase_price(15) == 65
    assert load_current_squad(squad).bank_tenths == 100


@pytest.mark.parametrize("stage", ["activation", "restoration"])
def test_free_hit_precommit_fault_keeps_both_stores_unchanged(finance_env, monkeypatch, stage):
    from fpl_manager.application import CommandBus, LiveContext
    database, squad, store = finance_env
    _appreciated_state(finance_env)
    CommandBus(database).initialize(LiveContext("alpha", "2026/27", 2))
    if stage == "restoration":
        execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2,
                          chip_played="FH", team_id="alpha")
    before = squad.read_bytes()
    with store._connect() as connection:
        decisions = connection.execute("SELECT * FROM decisions").fetchall()
        recommendations = connection.execute("SELECT * FROM decision_recommendations").fetchall()
        revisions = connection.execute("SELECT * FROM application_revisions").fetchall()

    def reject_commit(self):
        raise OSError("injected Free Hit precommit failure")

    monkeypatch.setattr(CommandBus, "_before_commit", reject_commit)
    with pytest.raises(OSError, match="precommit failure"):
        if stage == "activation":
            execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2,
                              chip_played="FH", team_id="alpha")
        else:
            advance_current_squad(squad, 3, team_id="alpha", database_path=database)
    assert squad.read_bytes() == before
    with store._connect() as connection:
        assert connection.execute("SELECT * FROM decisions").fetchall() == decisions
        assert connection.execute("SELECT * FROM decision_recommendations").fetchall() == recommendations
        assert connection.execute("SELECT * FROM application_revisions").fetchall() == revisions


@pytest.mark.parametrize("field,value", [
    ("bank_tenths", 100.5), ("gameweek", "2"), ("free_transfers", True),
    ("purchase_prices_tenths", {"15": 65}), ("chips_remaining", None),
])
def test_nested_lifecycle_snapshot_is_strictly_validated(finance_env, field, value):
    database, squad, _ = finance_env
    _appreciated_state(finance_env)
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2,
                      chip_played="FH", team_id="alpha")
    raw = json.loads(squad.read_text(encoding="utf-8"))
    raw["pre_free_hit_state"][field] = value
    squad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_current_squad(squad)


def test_free_hit_restore_publication_failure_recovers_after_restart(finance_env, monkeypatch):
    from fpl_manager.application import CommandBus, LiveContext, RecoveryRequiredError
    from fpl_manager.application import commands
    database, squad, _ = finance_env
    original = _appreciated_state(finance_env)
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2,
                      chip_played="FH", team_id="alpha")
    temporary = squad.read_bytes()

    def fail_publication(*args, **kwargs):
        raise OSError("injected FH restoration publication failure")

    with monkeypatch.context() as patch:
        patch.setattr(commands, "publish_file", fail_publication)
        with pytest.raises(RecoveryRequiredError):
            advance_current_squad(squad, 3, team_id="alpha", database_path=database)
    assert squad.read_bytes() == temporary
    CommandBus(database).recover(LiveContext("alpha", "2026/27", 3))
    restored = load_current_squad(squad)
    assert restored.player_ids == original.player_ids and restored.bank_tenths == 100
    assert restored.purchase_price(15) == 65 and restored.pre_free_hit_state is None
    assert get_gameweek_decision(2, team_id="alpha", database_path=database)["chip_played"] == "FH"


def test_legacy_undo_uses_latest_acquisition_after_prior_sale(finance_env):
    database, squad, store = finance_env
    original = _appreciated_state(finance_env, gameweek=3)
    # The GW2 human reacquisition at 65 supersedes their earlier acquisition at 55.
    for gw, price in ((1, 55), (2, 65)):
        record_gameweek_decision(
            gw, list(original.player_ids), STARTERS, BENCH, 13, 8, team_id="alpha",
            transfers=[{"outgoing_id": 16, "incoming_id": 15, "purchase_price_tenths": price}],
            database_path=database, capture_recommendations=False,
        )
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=3, team_id="alpha")
    raw = json.loads(squad.read_text(encoding="utf-8"))
    raw.pop("gameweek_start_state")
    squad.write_text(json.dumps(raw), encoding="utf-8")
    with store._connect() as connection, connection:
        row = connection.execute("SELECT id, transfers_json FROM decisions WHERE gameweek=3").fetchone()
        txs = json.loads(row[1])
        txs[0].pop("outgoing_purchase_price_tenths")
        connection.execute("UPDATE decisions SET transfers_json=? WHERE id=?", (json.dumps(txs), row[0]))
    undo_gameweek_changes(squad, 3, team_id="alpha", database_path=database)
    assert load_current_squad(squad).purchase_price(15) == 65
    assert load_current_squad(squad).bank_tenths == 100


@pytest.mark.parametrize("entry", ["lineup", "manual"])
def test_next_deadline_decision_does_not_log_free_hit_restoration_as_transfer(finance_env, entry):
    database, squad, _ = finance_env
    _appreciated_state(finance_env)
    execute_transfers(squad, [(15, 16)], database_path=database, gameweek=2,
                      chip_played="FH", team_id="alpha")
    decision = log_decision_from_current_squad(
        gameweek=3, squad_path=squad, database_path=database, team_id="alpha",
        transfers=["15:16"] if entry == "manual" else None,
    )
    restored = load_current_squad(squad)
    if entry == "lineup":
        assert decision["transfers"] == []
        assert restored.bank_tenths == 100 and restored.free_transfers == 1
    else:
        assert [(tx["outgoing_id"], tx["incoming_id"]) for tx in decision["transfers"]] == [(15, 16)]
        assert restored.bank_tenths == 117 and restored.purchase_price(16) == 50
    assert restored.pre_free_hit_state is None and decision["chip_played"] is None
