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
        assert player.minutes == 0
        assert player.expected_goals == 0.0
        assert store.search_latest_players("pla") == [{"id": 10, "name": "Player", "team": "EXA", "price_tenths": 75}]


def test_persists_and_loads_underlying_stats_and_events() -> None:
    bootstrap = {
        "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS"}],
        "events": [
            {"id": 1, "name": "Gameweek 1", "deadline_time": "2026-08-15T10:00:00Z", "is_current": False, "is_next": False, "finished": True},
            {"id": 2, "name": "Gameweek 2", "deadline_time": "2026-08-22T10:00:00Z", "is_current": True, "is_next": False, "finished": False},
        ],
        "elements": [
            {
                "id": 100,
                "web_name": "Saka",
                "team": 1,
                "element_type": 3,
                "now_cost": 100,
                "status": "d",
                "total_points": 18,
                "minutes": 170,
                "starts": 2,
                "chance_of_playing_next_round": 75,
                "chance_of_playing_this_round": 100,
                "expected_goals": "1.25",
                "expected_assists": "0.85",
                "expected_goal_involvements": "2.10",
                "expected_goals_conceded": "0.90",
                "expected_goals_per_90": 0.66,
                "expected_assists_per_90": 0.45,
                "expected_goals_conceded_per_90": 0.48,
                "clean_sheets_per_90": 0.5,
                "bps": 55,
                "ict_index": "18.2",
                "form": "9.0",
                "points_per_game": "9.0",
                "selected_by_percent": "35.5",
                "news": "Hamstring knock - 75% chance",
            }
        ],
    }
    fixtures = [{"id": 200, "event": 2, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 4, "kickoff_time": None, "finished": False}]
    with tempfile.TemporaryDirectory() as directory:
        store = SnapshotStore(Path(directory) / "fpl.sqlite3")
        store.save_snapshot(bootstrap, fixtures, "2026-08-20T12:00:00+00:00")
        summary = store.latest_summary()
        assert summary is not None
        assert summary["events"] == 2

        events = store.latest_events()
        assert len(events) == 2
        assert events[0]["name"] == "Gameweek 1"
        assert events[0]["finished"] is True
        assert events[1]["is_current"] is True

        player = store.latest_players()[0]
        assert player.name == "Saka"
        assert player.minutes == 170
        assert player.starts == 2
        assert player.chance_of_playing_next_round == 75
        assert player.expected_goals == 1.25
        assert player.expected_assists == 0.85
        assert player.expected_goal_involvements == 2.10
        assert player.bps == 55
        assert player.form == 9.0
        assert player.news == "Hamstring knock - 75% chance"


def test_migrates_legacy_database_columns() -> None:
    import sqlite3
    from contextlib import closing
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "legacy.sqlite3"
        with closing(sqlite3.connect(db_path)) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE snapshots (id INTEGER PRIMARY KEY, fetched_at TEXT NOT NULL UNIQUE);
                CREATE TABLE teams (snapshot_id INTEGER, team_id INTEGER, name TEXT, short_name TEXT, PRIMARY KEY (snapshot_id, team_id));
                CREATE TABLE players (
                    snapshot_id INTEGER, player_id INTEGER, web_name TEXT, team_id INTEGER, position_id INTEGER,
                    price_tenths INTEGER, status TEXT, total_points INTEGER, PRIMARY KEY (snapshot_id, player_id)
                );
                CREATE TABLE fixtures (
                    snapshot_id INTEGER, fixture_id INTEGER, event INTEGER, team_h INTEGER, team_a INTEGER,
                    kickoff_time TEXT, finished INTEGER, PRIMARY KEY (snapshot_id, fixture_id)
                );
                INSERT INTO snapshots VALUES (1, '2026-09-01T00:00:00+00:00');
                INSERT INTO teams VALUES (1, 1, 'Arsenal', 'ARS');
                INSERT INTO players VALUES (1, 50, 'LegacyPlayer', 1, 2, 60, 'a', 12);
                """
            )

        store = SnapshotStore(db_path)
        store.initialize()

        # Should load the player with migrated default values
        players = store.latest_players()
        assert len(players) == 1
        p = players[0]
        assert p.name == "LegacyPlayer"
        assert p.minutes == 0
        assert p.expected_goals == 0.0
        assert p.chance_of_playing_next_round is None


