import tempfile
from pathlib import Path

from fpl_manager.storage import SnapshotStore


def test_persists_and_loads_latest_snapshot() -> None:
    bootstrap = {
        "teams": [{"id": 1, "name": "Example", "short_name": "EXA"}],
        "elements": [{"id": 10, "web_name": "Player", "team": 1, "element_type": 3, "now_cost": 75, "status": "a", "total_points": 20}],
    }
    fixtures = [{"id": 100, "event": 1, "team_h": 1, "team_a": 2, "kickoff_time": None, "finished": False}]
    with tempfile.TemporaryDirectory() as directory:
        store = SnapshotStore(Path(directory) / "fpl.sqlite3")
        store.save_snapshot(bootstrap, fixtures, "2026-09-03T00:00:00+00:00")
        assert store.latest_summary() == {"snapshot_id": 1, "fetched_at": "2026-09-03T00:00:00+00:00", "players": 1, "teams": 1, "fixtures": 1}
        player = store.latest_players()[0]
        assert (player.id, player.price_tenths) == (10, 75)
        assert store.search_latest_players("pla") == [{"id": 10, "name": "Player", "team": "EXA", "price_tenths": 75}]
