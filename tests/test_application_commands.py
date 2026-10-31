"""Command boundary tests use only fixture-owned SQLite and state files."""

import json
import multiprocessing
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from fpl_manager.application import (
    CommandBus,
    CommandContextError,
    HistoricalContext,
    IdempotencyConflictError,
    InvalidCommandError,
    LiveContext,
    RecoveryConflictError,
    RecoveryRequiredError,
    StaleRevisionError,
    active_command,
)
from fpl_manager.application import commands
from fpl_manager.application import files as application_files
from fpl_manager.application.files import delete_state_file, read_state_text, state_file_exists, write_state_text
from fpl_manager.storage import SnapshotStore


@pytest.fixture
def context():
    return LiveContext("fixture-team", "2026-27", 1)


@pytest.fixture
def state(tmp_path):
    database = tmp_path / "data" / "fpl.sqlite3"
    squad = tmp_path / "private" / "squad.json"
    write_state_text(squad, '{"bank": 100}')
    return database, squad


def insert_snapshot(database: Path, label: str = "fixture"):
    store = SnapshotStore(database)
    store.initialize()
    with closing(store._connect()) as connection, connection:
        connection.execute("INSERT INTO snapshots(fetched_at) VALUES (?)", (label,))


def snapshot_count(database: Path):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]


def increment(database: Path, squad: Path, label: str = "fixture"):
    before = json.loads(read_state_text(squad))
    insert_snapshot(database, label)
    write_state_text(squad, json.dumps({"bank": before["bank"] + 1}))
    assert json.loads(read_state_text(squad)) == {"bank": before["bank"] + 1}
    return {"bank": before["bank"] + 1}


def test_command_operation_logs_exclude_payload(context, state, caplog):
    database, squad = state
    with caplog.at_level("INFO", logger="fpl_manager.application.commands"):
        receipt = CommandBus(database).execute(
            context, "fixture-change", {"notes": "private-fixture-notes", "api_key": "not-a-real-secret"},
            lambda: increment(database, squad), command_id="logged-command",
        )
    assert receipt.revision_after == 1
    assert "command_committed" in caplog.text
    assert "logged-command" in caplog.text
    assert "fixture-team" in caplog.text
    assert "private-fixture-notes" not in caplog.text
    assert "not-a-real-secret" not in caplog.text


def crash_publish(*args):
    raise OSError("fixture: file publication unavailable")


def competing_process(database, squad, barrier, queue, index):
    context = LiveContext("fixture-team", "2026-27", 1)
    bus = CommandBus(Path(database))
    barrier.wait(timeout=30)
    try:
        receipt = bus.execute(
            context, "process-command", {"index": index},
            lambda: increment(Path(database), Path(squad), str(index)), expected_revision=0,
        )
        queue.put(("committed", receipt.revision_after))
    except (StaleRevisionError, RecoveryRequiredError) as error:
        queue.put((error.code, error.details["revision"]))


def test_contexts_are_explicit_frozen_and_revisions_exclude_gameweek(context):
    assert context.key == LiveContext("fixture-team", "2026-27", 2).key
    assert context.key != LiveContext("fixture-team", "2025-26", 1).key
    assert context.key != HistoricalContext("fixture-team", "2026-27", 1).key
    with pytest.raises(AttributeError):
        context.gameweek = 2
    for identifier in ("", " ", ".", "..", "../team", "a/b", "a\\b", "C:team", "\0"):
        with pytest.raises(ValueError):
            LiveContext(identifier, "2026-27", 1)
    with pytest.raises(ValueError):
        HistoricalContext("session", "", 1)


def test_valid_command_commits_sql_file_and_durable_receipt(state, context):
    database, squad = state
    receipt = CommandBus(database).execute(
        context, "transfer", {"in": [2], "out": [1]},
        lambda: increment(database, squad), expected_revision=0, command_id="fixture-command",
    )
    assert receipt.to_dict() == {
        "result": {"bank": 101}, "revision_before": 0, "revision_after": 1, "command_id": "fixture-command"
    }
    assert snapshot_count(database) == 1
    assert json.loads(squad.read_text()) == {"bank": 101}
    assert CommandBus(database).revision(LiveContext(context.team_id, context.season, 2)) == 1
    with closing(sqlite3.connect(database)) as connection:
        fingerprint, state_value = connection.execute(
            "SELECT fingerprint, state FROM application_commands"
        ).fetchone()
    assert len(fingerprint) == 64
    assert state_value == "complete"
    assert active_command() is None


@pytest.mark.parametrize("fail_after_action", [False, True])
def test_action_or_precommit_failure_rolls_back_sql_and_discards_files(
    state, context, monkeypatch, fail_after_action
):
    database, squad = state
    bus = CommandBus(database)
    before = squad.read_bytes()

    def fail():
        raise ValueError("fixture validation failure")

    def action():
        increment(database, squad)
        if not fail_after_action:
            fail()
        return {"ok": True}

    if fail_after_action:
        monkeypatch.setattr(bus, "_before_commit", fail)
    with pytest.raises(ValueError):
        bus.execute(context, "invalid", {}, action)
    assert squad.read_bytes() == before
    assert snapshot_count(database) == 0
    assert bus.revision(context) == 0
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM application_commands").fetchone()[0] == 0
    assert active_command() is None


def test_fresh_bus_recovers_committed_sql_and_files_exactly_once(state, context, monkeypatch):
    database, squad = state
    bus = CommandBus(database)
    monkeypatch.setattr(bus, "_publish", crash_publish)
    with pytest.raises(RecoveryRequiredError) as failure:
        bus.execute(context, "transfer", {}, lambda: increment(database, squad), command_id="recover-me")
    assert failure.value.details == {
        "command_id": "recover-me", "revision": 1, "state": "pending", "context": context.to_dict()
    }
    assert snapshot_count(database) == 1
    assert json.loads(squad.read_text()) == {"bank": 100}
    fresh = CommandBus(database)
    with pytest.raises(RecoveryRequiredError):
        fresh.revision(context)
    with pytest.raises(RecoveryRequiredError):
        fresh.execute(context, "different-command", {}, lambda: pytest.fail("must not run"))
    assert [receipt.command_id for receipt in fresh.recover()] == ["recover-me"]
    assert fresh.recover() == []
    assert json.loads(squad.read_text()) == {"bank": 101}
    assert snapshot_count(database) == 1
    assert fresh.revision(context) == 1


@pytest.mark.parametrize("raise_after_commit", [False, True])
def test_commit_failure_distinguishes_rolled_back_from_durably_committed(
    state, context, monkeypatch, raise_after_commit
):
    database, squad = state
    bus = CommandBus(database)

    class FailingCommit(sqlite3.Connection):
        def commit(self):
            if raise_after_commit:
                super().commit()
            raise OSError("fixture: commit acknowledgement failure")

    def connect(path, **kwargs):
        return sqlite3.connect(path, factory=FailingCommit)

    monkeypatch.setattr(bus, "_connect", connect)
    if raise_after_commit:
        with pytest.raises(RecoveryRequiredError):
            bus.execute(context, "commit-failure", {}, lambda: increment(database, squad))
        assert snapshot_count(database) == 1
        assert len(CommandBus(database).recover()) == 1
        assert json.loads(squad.read_text()) == {"bank": 101}
    else:
        with pytest.raises(OSError):
            bus.execute(context, "commit-failure", {}, lambda: increment(database, squad))
        assert snapshot_count(database) == 0
        assert json.loads(squad.read_text()) == {"bank": 100}
        assert CommandBus(database).revision(context) == 0


def test_same_command_id_recovers_before_expected_revision_check(state, context, monkeypatch):
    database, squad = state
    first = CommandBus(database)
    monkeypatch.setattr(first, "_publish", crash_publish)
    with pytest.raises(RecoveryRequiredError):
        first.execute(
            context, "transfer", {"player": 1}, lambda: increment(database, squad),
            command_id="retry-me", expected_revision=0,
        )
    receipt = CommandBus(database).execute(
        context, "transfer", {"player": 1}, lambda: pytest.fail("must replay"),
        command_id="retry-me", expected_revision=0,
    )
    assert receipt.result == {"bank": 101}
    assert receipt.revision_after == 1
    assert snapshot_count(database) == 1


def test_partial_file_publication_recovery(state, context, monkeypatch):
    database, squad = state
    other = squad.with_name("metadata.json")
    write_state_text(other, '{"active": false}')
    original_publish = commands.publish_file
    calls = 0

    def publish_one_then_crash(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fixture crash between files")
        original_publish(*args)

    def action():
        increment(database, squad)
        write_state_text(other, '{"active": true}')
        return {"ok": True}

    monkeypatch.setattr(commands, "publish_file", publish_one_then_crash)
    with pytest.raises(RecoveryRequiredError):
        CommandBus(database).execute(context, "two-files", {}, action)
    assert json.loads(squad.read_text()) == {"bank": 101}
    assert json.loads(other.read_text()) == {"active": False}
    monkeypatch.setattr(commands, "publish_file", original_publish)
    assert len(CommandBus(database).recover()) == 1
    assert json.loads(other.read_text()) == {"active": True}
    assert snapshot_count(database) == 1


def test_all_files_published_but_completion_failure_recovers_without_rewriting(state, context, monkeypatch):
    database, squad = state
    bus = CommandBus(database)
    real_publish = bus._publish
    real_replace = application_files.os.replace
    replacements = []

    def replace(source, target):
        replacements.append(str(target))
        real_replace(source, target)

    def finish_then_crash(connection, row):
        real_publish(connection, row)
        raise OSError("fixture: completion commit unavailable")

    monkeypatch.setattr(application_files.os, "replace", replace)
    monkeypatch.setattr(bus, "_publish", finish_then_crash)
    with pytest.raises(RecoveryRequiredError):
        bus.execute(context, "complete-crash", {}, lambda: increment(database, squad))
    assert json.loads(squad.read_text()) == {"bank": 101}
    assert len(CommandBus(database).recover()) == 1
    assert replacements == [str(squad.resolve())]
    assert snapshot_count(database) == 1
    assert CommandBus(database).revision(context) == 1


def test_external_edit_blocks_recovery_without_overwriting(state, context, monkeypatch):
    database, squad = state
    bus = CommandBus(database)
    monkeypatch.setattr(bus, "_publish", crash_publish)
    with pytest.raises(RecoveryRequiredError):
        bus.execute(context, "transfer", {}, lambda: increment(database, squad), command_id="conflict")
    squad.write_text('{"bank": 999}', encoding="utf-8")
    fresh = CommandBus(database)
    with pytest.raises(RecoveryConflictError) as error:
        fresh.recover()
    assert error.value.code == "RECOVERY_CONFLICT"
    assert error.value.details["command_id"] == "conflict"
    assert json.loads(squad.read_text()) == {"bank": 999}
    with pytest.raises(RecoveryRequiredError):
        fresh.revision(context)
    assert snapshot_count(database) == 1
    squad.write_text('{"bank": 100}', encoding="utf-8")
    fresh.recover()
    assert json.loads(squad.read_text()) == {"bank": 101}


def test_external_edit_during_atomic_publication_is_not_overwritten(state, context, monkeypatch):
    database, squad = state
    real_fsync = application_files.os.fsync

    def edit_after_fsync(descriptor):
        real_fsync(descriptor)
        squad.write_text('{"bank": 999}', encoding="utf-8")

    monkeypatch.setattr(application_files.os, "fsync", edit_after_fsync)
    with pytest.raises(RecoveryConflictError):
        CommandBus(database).execute(context, "external-publication-conflict", {}, lambda: increment(database, squad))
    assert json.loads(squad.read_text()) == {"bank": 999}
    assert snapshot_count(database) == 1
    assert list(squad.parent.glob("*.stage")) == []


def test_duplicate_id_returns_persisted_receipt_without_double_effects(state, context):
    database, squad = state
    first = CommandBus(database).execute(
        context, "transfer", {"out": (1,), "in": [2]},
        lambda: increment(database, squad), command_id="duplicate", expected_revision=0,
    )
    repeated = CommandBus(database).execute(
        context, "transfer", {"in": [2], "out": [1]},
        lambda: pytest.fail("must not apply twice"), command_id="duplicate", expected_revision=0,
    )
    assert repeated.to_dict() == first.to_dict()
    assert snapshot_count(database) == 1
    for changed_context, operation, payload in (
        (context, "transfer", {"in": [3], "out": [1]}),
        (LiveContext("other-team", context.season, 1), "transfer", {"in": [2], "out": [1]}),
        (LiveContext(context.team_id, context.season, 2), "transfer", {"in": [2], "out": [1]}),
        (context, "other-operation", {"in": [2], "out": [1]}),
    ):
        with pytest.raises(IdempotencyConflictError):
            CommandBus(database).execute(
                changed_context, operation, payload, lambda: pytest.fail("must not run"), command_id="duplicate"
            )


def test_two_fresh_buses_serialize_expected_revision_zero(state, context):
    database, squad = state
    barrier = threading.Barrier(2)

    def run(index):
        bus = CommandBus(database)
        barrier.wait(timeout=10)
        try:
            return bus.execute(
                context, "concurrent", {"index": index},
                lambda: increment(database, squad, str(index)), expected_revision=0,
            )
        except StaleRevisionError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(run, (1, 2)))
    assert sum(isinstance(result, StaleRevisionError) for result in results) == 1
    assert snapshot_count(database) == 1
    assert json.loads(squad.read_text()) == {"bank": 101}
    assert CommandBus(database).revision(context) == 1


def test_separate_processes_use_sqlite_not_only_memory_locks(state, context):
    database, squad = state
    process_context = multiprocessing.get_context("spawn")
    barrier = process_context.Barrier(2)
    queue = process_context.Queue()
    processes = [
        process_context.Process(
            target=competing_process, args=(str(database), str(squad), barrier, queue, index)
        )
        for index in (1, 2)
    ]
    try:
        for process in processes:
            process.start()
        results = [queue.get(timeout=45), queue.get(timeout=45)]
        for process in processes:
            process.join(timeout=10)
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
        queue.close()
        queue.join_thread()
    assert sum(code == "committed" for code, _ in results) == 1
    assert all(revision == 1 for _, revision in results)
    assert any(code in {"STALE_REVISION", "RECOVERY_REQUIRED"} for code, _ in results)
    CommandBus(database).recover()
    assert snapshot_count(database) == 1
    assert json.loads(squad.read_text()) == {"bank": 101}


def test_nested_public_mutator_and_legacy_connection_scopes_share_outer_commit(state, context):
    database, squad = state

    def nested():
        store = SnapshotStore(database)
        store.initialize()
        with closing(store._connect()) as connection, connection:
            connection.execute("INSERT INTO snapshots(fetched_at) VALUES ('nested')")
            connection.commit()
            connection.close()
            cursor = connection.cursor()
            cursor.connection.commit()
            cursor.connection.close()
            assert connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
        write_state_text(squad, '{"bank": 88}')
        assert json.loads(read_state_text(squad)) == {"bank": 88}
        assert json.loads(squad.read_text()) == {"bank": 100}
        with closing(sqlite3.connect(database)) as independent:
            assert independent.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
        return {"bank": 88}

    def outer():
        scope = active_command(context)
        result = CommandBus(database).execute(context, "finance-nested", {}, nested)
        assert result.command_id == scope.command_id
        return result.result

    receipt = CommandBus(database).execute(context, "outer", {}, outer)
    assert receipt.result == {"bank": 88}
    assert snapshot_count(database) == 1
    assert CommandBus(database).revision(context) == 1
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM application_commands").fetchone()[0] == 1


def test_caught_nested_failure_still_rolls_back_outer(state, context):
    database, squad = state

    def fail():
        increment(database, squad)
        raise ValueError("nested failure")

    def outer():
        try:
            CommandBus(database).execute(context, "nested", {}, fail)
        except ValueError:
            return {"caught": True}

    with pytest.raises(InvalidCommandError, match="roll back"):
        CommandBus(database).execute(context, "outer", {}, outer)
    assert snapshot_count(database) == 0
    assert json.loads(squad.read_text()) == {"bank": 100}


def test_cross_context_and_cross_database_nested_mutations_rejected(state, context):
    database, squad = state
    other = LiveContext("other", context.season, context.gameweek)
    for nested_context, nested_database in ((other, database), (context, database.with_name("other.sqlite3"))):
        with pytest.raises(CommandContextError):
            CommandBus(database).execute(
                context, "outer", {},
                lambda: CommandBus(nested_database).execute(
                    nested_context, "nested", {}, lambda: increment(database, squad)
                ),
            )
    assert not database.with_name("other.sqlite3").exists()
    assert snapshot_count(database) == 0


@pytest.mark.parametrize("sql", ["COMMIT", "ROLLBACK", "END", "SAVEPOINT nested"])
def test_borrowed_sql_cannot_end_the_outer_transaction(state, context, sql):
    database, squad = state

    def action():
        increment(database, squad)
        active_command().connection.cursor().execute(sql)

    with pytest.raises(sqlite3.DatabaseError, match="authorized"):
        CommandBus(database).execute(context, "invalid-transaction", {}, action)
    assert snapshot_count(database) == 0
    assert json.loads(squad.read_text()) == {"bank": 100}


def test_revision_reads_do_not_create_initialize_migrate_or_recover(state, context, monkeypatch):
    database, squad = state
    bus = CommandBus(database)
    monkeypatch.setattr(bus, "initialize", lambda *_: pytest.fail("a read cannot initialize"))
    assert bus.revision(context) == 0
    assert not database.exists()
    assert bus.recover() == []
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE unrelated(value TEXT)")
    before = database.read_bytes()
    assert bus.revision(context) == 0
    assert database.read_bytes() == before
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("unrelated",)]


def test_query_revision_uses_one_snapshot_across_a_concurrent_commit(tmp_path, monkeypatch):
    from fpl_manager.application.services import ApplicationService
    from fpl_manager.squad_state import CurrentSquadState, load_current_squad, save_current_squad

    database = tmp_path / "state.sqlite3"
    config = tmp_path / "config"
    squad = config / "teams" / "fixture" / "squad.json"
    context = LiveContext("fixture", "2026/27", 1)
    initial = CurrentSquadState(
        tuple(range(1, 16)), {pid: 50 for pid in range(1, 16)},
        0, 1, (), context.season, 1, 1,
    )
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
    CommandBus(database).execute(context, "seed", {}, lambda: save_current_squad(squad, initial))
    committed = threading.Event()
    allow_publication = threading.Event()
    finished = threading.Event()
    errors = []

    class DelayedPublisher(CommandBus):
        def _publish(self, connection, row):
            committed.set()
            if not allow_publication.wait(10):
                raise RuntimeError("Fixture publication gate timed out.")
            return super()._publish(connection, row)

    writer = DelayedPublisher(database)
    writer.initialize(context)

    def mutate():
        try:
            writer.execute(
                context, "change", {},
                lambda: save_current_squad(squad, replace(initial, bank_tenths=1)),
            )
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    thread = threading.Thread(target=mutate)
    service = ApplicationService(database, config)
    original_pending = service.commands._pending
    started = False

    def commit_after_pending_read(connection):
        nonlocal started
        pending = original_pending(connection)
        if pending is None and not started:
            started = True
            thread.start()
            assert committed.wait(10), "Fixture commit gate timed out."
        return pending

    monkeypatch.setattr(service.commands, "_pending", commit_after_pending_read)

    def calculate():
        observed = load_current_squad(squad).bank_tenths
        allow_publication.set()
        assert finished.wait(10), "Fixture completion gate timed out."
        return {"bank_tenths": observed}

    try:
        with pytest.raises(StaleRevisionError) as error:
            service.query(context, "/api/squad", calculate)
        assert error.value.details["expected_revision"] == 1
        assert error.value.details["revision"] == 2
    finally:
        allow_publication.set()
        if started:
            thread.join(timeout=10)
            assert not thread.is_alive()
    assert errors == []
    assert load_current_squad(squad).bank_tenths == 1
    assert CommandBus(database).revision(context) == 2


def test_historical_routes_to_control_database_without_opening_live_sql(tmp_path, monkeypatch):
    live = tmp_path / "data" / "fpl.sqlite3"
    control = tmp_path / "config" / "simulations" / "command_journal.sqlite3"
    session_file = control.parent / "fixture-session.json"
    context = HistoricalContext("fixture-session", "2023-24", 1)
    real_connect = sqlite3.connect
    opened = []

    def track_connect(database, *args, **kwargs):
        opened.append(str(database))
        assert "fpl.sqlite3" not in str(database)
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", track_connect)
    bus = CommandBus(live)
    assert bus.revision(context) == 0
    assert bus.recover(context) == []
    assert not live.exists()
    receipt = bus.execute(
        context, "advance", {}, lambda: write_state_text(session_file, '{"gameweek": 2}')
    )
    assert receipt.revision_after == 1
    assert bus.revision(HistoricalContext("fixture-session", "2023-24", 2)) == 1
    assert not live.exists()
    assert control.exists()
    assert json.loads(session_file.read_text()) == {"gameweek": 2}
    assert opened
    with closing(real_connect(control)) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='players'").fetchone() is None


def test_historical_pending_recovery_does_not_open_live_database(tmp_path, monkeypatch):
    live = tmp_path / "data" / "fpl.sqlite3"
    control = tmp_path / "config" / "simulations" / "command_journal.sqlite3"
    session_file = control.parent / "session.json"
    context = HistoricalContext("session", "2023-24", 1)
    bus = CommandBus(live)
    monkeypatch.setattr(bus, "_publish", crash_publish)
    with pytest.raises(RecoveryRequiredError):
        bus.execute(context, "advance", {}, lambda: write_state_text(session_file, '{"gw": 2}'))
    assert not live.exists()
    assert len(CommandBus(control).recover()) == 1
    assert json.loads(session_file.read_text()) == {"gw": 2}
    assert not live.exists()


def test_historical_active_command_rejects_live_storage_access(tmp_path):
    live = tmp_path / "data" / "fpl.sqlite3"
    control = tmp_path / "config" / "simulations" / "command_journal.sqlite3"
    context = HistoricalContext("session", "2023-24", 1)
    with pytest.raises(CommandContextError):
        CommandBus(control).execute(context, "bad-storage", {}, lambda: SnapshotStore(live).initialize())
    assert not live.exists()
    assert CommandBus(control).revision(context) == 0


def test_staged_deletion_and_read_your_writes(state, context):
    database, squad = state

    def action():
        delete_state_file(squad)
        assert squad.exists()
        assert not state_file_exists(squad)
        with pytest.raises(FileNotFoundError):
            read_state_text(squad)
        write_state_text(squad, '{"bank": 55}')
        assert state_file_exists(squad)
        assert json.loads(read_state_text(squad)) == {"bank": 55}
        delete_state_file(squad)
        return {"deleted": True}

    receipt = CommandBus(database).execute(context, "delete", {}, action)
    assert receipt.result == {"deleted": True}
    assert not squad.exists()


def test_new_staged_files_are_visible_without_creating_actual_files(state, context):
    database, squad = state
    session_file = squad.parent / "new-session.json"
    assert not state_file_exists(session_file)

    def action():
        write_state_text(session_file, '{"gameweek": 1}')
        assert not session_file.exists()
        assert state_file_exists(session_file)
        assert read_state_text(session_file) == '{"gameweek": 1}'
        write_state_text(session_file, '{"gameweek": 2}')
        assert read_state_text(session_file) == '{"gameweek": 2}'
        return {"ok": True}

    CommandBus(database).execute(context, "new-session", {}, action)
    assert state_file_exists(session_file)
    assert read_state_text(session_file) == '{"gameweek": 2}'


def test_delete_recovery_and_external_recreation_conflict(state, context, monkeypatch):
    database, squad = state
    bus = CommandBus(database)
    monkeypatch.setattr(bus, "_publish", crash_publish)
    with pytest.raises(RecoveryRequiredError):
        bus.execute(context, "delete", {}, lambda: delete_state_file(squad))
    squad.write_text('{"external": true}', encoding="utf-8")
    with pytest.raises(RecoveryConflictError):
        CommandBus(database).recover()
    assert squad.exists()
    squad.write_text('{"bank": 100}', encoding="utf-8")
    CommandBus(database).recover()
    assert not squad.exists()


def test_non_json_payload_or_result_fails_without_state_effects(state, context):
    database, squad = state
    bus = CommandBus(database)
    for payload in ({"unsupported": object()}, {"nan": float("nan")}, {1: "not-string-key"}):
        with pytest.raises(InvalidCommandError):
            bus.execute(context, "invalid", payload, lambda: pytest.fail("must not run"))
    assert not database.exists()

    def invalid_result():
        increment(database, squad)
        return object()

    with pytest.raises(InvalidCommandError):
        bus.execute(context, "unsupported-result", {}, invalid_result)
    assert snapshot_count(database) == 0
    assert json.loads(squad.read_text()) == {"bank": 100}


def test_to_dict_results_and_atomic_compatibility_writes(state, context):
    database, squad = state

    @dataclass
    class Result:
        bank: int

        def to_dict(self):
            return {"bank": self.bank}

    receipt = CommandBus(database).execute(context, "dataclass", {}, lambda: Result(101))
    assert receipt.result == {"bank": 101}
    write_state_text(squad, '{"bank": 5}')
    assert read_state_text(squad) == '{"bank": 5}'
    assert list(squad.parent.glob("*.stage")) == []


def test_file_changed_during_action_rolls_back_sql(state, context):
    database, squad = state

    def action():
        assert json.loads(read_state_text(squad)) == {"bank": 100}
        squad.write_text('{"bank": 999}', encoding="utf-8")
        insert_snapshot(database)
        write_state_text(squad, '{"bank": 101}')

    with pytest.raises(InvalidCommandError, match="changed"):
        CommandBus(database).execute(context, "external-conflict", {}, action)
    assert snapshot_count(database) == 0
    assert json.loads(squad.read_text()) == {"bank": 999}


def test_ambient_scope_cannot_be_used_on_another_thread(state, context):
    database, _ = state

    def action():
        scope = active_command()
        with ThreadPoolExecutor(max_workers=1) as executor:
            with pytest.raises(InvalidCommandError, match="another thread"):
                executor.submit(lambda: scope.connection.execute("SELECT 1")).result()
        return {"ok": True}

    assert CommandBus(database).execute(context, "thread-safety", {}, action).result == {"ok": True}
