"""Adversarial HTTP checks using real journal transactions and isolated files."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import urllib.error
import urllib.request

import pytest

from fpl_manager.application import CommandBus, HistoricalContext, StaleRevisionError
from fpl_manager.application.services import ApplicationService
from fpl_manager.gui.server import FPLRequestHandler, ThreadingHTTPServer
from fpl_manager.simulation import HistoricalSimulationSession


@pytest.fixture
def application_server(tmp_path):
    config = tmp_path / "config"

    class Handler(FPLRequestHandler):
        config_dir = config
        database_path = tmp_path / "live.sqlite3"

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = HistoricalSimulationSession.create(
        "commands", "2023-24", config_dir=config / "simulations",
    )
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path, body=None):
        encoded = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            base + path, data=encoded, headers={"Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    yield request, session, Handler.database_path
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def command_body(request, command_id):
    status, state = request("/api/historical/simulations/commands")
    assert status == 200
    return {
        "command_context": state["command_context"], "expected_revision": state["revision"],
        "command_id": command_id,
    }


def test_http_retry_returns_original_receipt_after_deadline_advanced(application_server):
    request, session, live_database = application_server
    body = command_body(request, "advance-once")
    status, first = request("/api/historical/simulations/commands/run-gw", body)
    assert status == 200, first
    status, repeated = request("/api/historical/simulations/commands/run-gw", body)
    assert status == 200 and repeated == first
    loaded = HistoricalSimulationSession.load("commands", config_dir=session.config_dir)
    assert loaded.current_gw == 2 and len(loaded.history) == 1
    assert not live_database.exists()


def test_http_stale_concurrent_commands_have_one_winner(application_server):
    request, session, _ = application_server
    body = command_body(request, "first")
    second = {**body, "command_id": "second"}
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(
            lambda value: request("/api/historical/simulations/commands/chip", value),
            [body, second],
        ))
    assert sorted(status for status, _ in outcomes) == [200, 409]
    conflict = next(result for status, result in outcomes if status == 409)
    assert conflict["code"] == "STALE_REVISION"
    context = HistoricalContext("commands", session.season, session.current_gw)
    journal = session.config_dir / "command_journal.sqlite3"
    assert CommandBus(journal, historical_database_path=journal).revision(context) == body["expected_revision"] + 1


def test_http_invalid_lineup_does_not_consume_chip_or_write_file(application_server):
    request, session, _ = application_server
    body = command_body(request, "bad-lineup")
    path = session.config_dir / "commands.json"
    before = path.read_bytes()
    status, result = request("/api/decisions", {
        **body, "session_id": "commands", "gameweek": 1, "chip": "triple_captain",
        "captain_id": session.captain_id, "vice_captain_id": session.captain_id,
    })
    assert status == 400, result
    assert path.read_bytes() == before
    status, state = request("/api/historical/simulations/commands")
    assert status == 200 and state["revision"] == body["expected_revision"]


def test_http_postcommit_failure_is_explicit_and_recoverable(application_server, monkeypatch):
    request, session, _ = application_server
    body = command_body(request, "interrupted-publication")
    path = session.config_dir / "commands.json"
    before = path.read_bytes()

    def fail_publication(*args):
        raise OSError("injected replacement failure")

    with monkeypatch.context() as scoped:
        scoped.setattr("fpl_manager.application.commands.publish_file", fail_publication)
        status, result = request("/api/historical/simulations/commands/chip", {**body, "chip": "triple_captain"})
        assert status == 409 and result["code"] == "RECOVERY_REQUIRED"
        assert path.read_bytes() == before
    journal = session.config_dir / "command_journal.sqlite3"
    recovered = CommandBus(journal, historical_database_path=journal).recover()
    assert len(recovered) == 1
    status, state = request("/api/historical/simulations/commands")
    assert status == 200
    assert state["active_chip"] == "triple_captain"
    assert state["revision"] == body["expected_revision"] + 1


def test_http_legacy_archive_requires_explicit_fork(application_server):
    request, session, live_database = application_server
    path = session.config_dir / "commands.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("execution_version")
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    status, archive = request("/api/historical/simulations/commands")
    assert status == 200 and archive["read_only"]
    status, rejected = request("/api/historical/simulations/commands/chip", {"chip": "triple_captain"})
    assert status == 409 and rejected["code"] == "LEGACY_TRIAL_READ_ONLY"
    status, fork = request("/api/historical/simulations/commands/fork", {"new_session_id": "corrected"})
    assert status == 200, fork
    assert fork["session_id"] == "corrected"
    assert path.read_bytes() == before
    assert not live_database.exists()


def test_query_rejects_a_mixed_revision_read(application_server):
    _, session, database = application_server
    service = ApplicationService(database, session.config_dir.parent)
    context = service.historical_context(session.session_id)

    def raced_query():
        session.play_chip("triple_captain")
        return {"bank_tenths": session.bank_tenths}

    with pytest.raises(StaleRevisionError):
        service.query(context, "/api/squad", raced_query)
