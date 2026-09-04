"""Tests for LLM Advisory Layer with Deterministic Guardrails."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from fpl_manager.llm_advisor import (
    generate_llm_advisory,
    validate_proposed_advisory_actions,
)
from fpl_manager.squad_state import load_current_squad
from fpl_manager.storage import SnapshotStore, utc_timestamp


@pytest.fixture
def advisor_test_env(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "fpl.sqlite3"
    squad_path = tmp_path / "current_squad.json"

    store = SnapshotStore(db_path)
    store.initialize()

    bootstrap = {
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Liverpool", "short_name": "LIV"},
            {"id": 3, "name": "Manchester City", "short_name": "MCI"},
            {"id": 4, "name": "Chelsea", "short_name": "CHE"},
            {"id": 5, "name": "Tottenham", "short_name": "TOT"},
        ],
        "events": [
            {"id": 1, "name": "Gameweek 1", "deadline_time": "2026-08-15T10:00:00Z", "is_current": True, "finished": False},
        ],
        "elements": [],
    }

    # 18 players: 1-15 in squad, 16-18 outside squad
    # Pos: 1-2 GKP, 3-7 DEF, 8-12 MID, 13-15 FWD, 16-18 FWD
    for p_id in range(1, 19):
        pos_id = 1 if p_id <= 2 else (2 if p_id <= 7 else (3 if p_id <= 12 else 4))
        bootstrap["elements"].append({
            "id": p_id,
            "web_name": f"Player_{p_id}",
            "team": 3 if p_id == 16 else (((p_id - 1) % 5) + 1),
            "element_type": pos_id,
            "now_cost": 50,
            "status": "a",
            "chance_of_playing_next_round": 100,
            "news": "",
            "total_points": 20,
            "selected_by_percent": 15.0,
        })

    fixtures = [
        {"id": 1, "event": 1, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 3, "kickoff_time": "2026-08-15T11:30:00Z", "finished": False},
    ]

    store.save_snapshot(bootstrap, fixtures, utc_timestamp())

    squad_data = {
        "season": "2026/27",
        "free_transfers": 1,
        "bank_tenths": 10,
        "chips_remaining": ["wildcard"],
        "player_ids": list(range(1, 16)),
        "purchase_prices_tenths": {str(i): 50 for i in range(1, 16)},
        "gameweek": 1,
    }
    squad_path.write_text(json.dumps(squad_data, indent=2), encoding="utf-8")

    return db_path, squad_path


def test_heuristic_advisory_devil_advocate(advisor_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = advisor_test_env

    advisory = generate_llm_advisory(
        gameweek=1,
        squad_path=squad_path,
        database_path=db_path,
        persona="devil_advocate",
        provider="heuristic",
        save_reports=False,
    )

    assert advisory["gameweek"] == 1
    assert advisory["persona"] == "devil_advocate"
    assert "heuristic" in advisory["provider_used"]
    assert "Devil's Advocate" in advisory["analysis_markdown"]
    assert advisory["validation"]["is_legal"] is True
    assert "APPROVED (LEGAL & WITHIN BUDGET)" in advisory["markdown"]


def test_heuristic_advisory_tactical_and_strategic(advisor_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = advisor_test_env

    advisory_tac = generate_llm_advisory(
        gameweek=1,
        squad_path=squad_path,
        database_path=db_path,
        persona="tactical_analyst",
        provider="heuristic",
        save_reports=False,
    )
    assert "Tactical & Press Conference" in advisory_tac["analysis_markdown"]

    advisory_strat = generate_llm_advisory(
        gameweek=1,
        squad_path=squad_path,
        database_path=db_path,
        persona="strategic_planner",
        provider="heuristic",
        save_reports=False,
    )
    assert "Strategic Macro Blueprint" in advisory_strat["analysis_markdown"]


def test_validation_guardrails_detect_illegal_moves(advisor_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = advisor_test_env
    store = SnapshotStore(db_path)
    state = load_current_squad(squad_path)
    all_players = store.latest_players()

    # Case 1: Proposed captain not in squad
    val_cap = validate_proposed_advisory_actions(
        state=state,
        all_players=all_players,
        proposed_transfers=[],
        proposed_captain="Player_18",  # Player 18 is not in squad
        proposed_vice_captain="Player_1",
    )
    assert val_cap["is_legal"] is False
    assert val_cap["captain_valid"] is False
    assert any("not in current squad" in err for err in val_cap["errors"])

    # Case 2: Illegal transfer - outgoing player not in squad
    val_trans_out = validate_proposed_advisory_actions(
        state=state,
        all_players=all_players,
        proposed_transfers=[{"out": "Player_18", "in": "Player_16"}],
        proposed_captain="Player_1",
        proposed_vice_captain="Player_2",
    )
    assert val_trans_out["is_legal"] is False
    assert any("not in the current squad" in err for err in val_trans_out["errors"])

    # Case 3: Legal transfer: Player 13 (FWD) out -> Player 16 (FWD, team 1) in
    val_legal = validate_proposed_advisory_actions(
        state=state,
        all_players=all_players,
        proposed_transfers=[{"out": "Player_13", "in": "Player_16", "rationale": "Form upgrade"}],
        proposed_captain="Player_1",
        proposed_vice_captain="Player_2",
    )
    assert val_legal["is_legal"] is True
    assert val_legal["transfers_valid"] is True
    assert len(val_legal["validated_transfers"]) == 1


def test_llm_advisory_with_mocked_llm_response(advisor_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = advisor_test_env

    mock_response = """
    Here is my tactical critique:
    The fixture against Liverpool looks treacherous for our defense. We should bench Player_3.

    ```json
    {
        "captain": "Player_1",
        "vice_captain": "Player_2",
        "transfers": [
            {
                "out": "Player_13",
                "in": "Player_16",
                "rationale": "Targeting easy fixture"
            }
        ]
    }
    ```
    """

    with patch("fpl_manager.llm_advisor._call_gemini_api", return_value=mock_response):
        advisory = generate_llm_advisory(
            gameweek=1,
            squad_path=squad_path,
            database_path=db_path,
            provider="gemini",
            api_key="fake-gemini-key",
            save_reports=False,
        )

        assert advisory["provider_used"] == "gemini"
        assert advisory["proposed_captain"] == "Player_1"
        assert advisory["validation"]["is_legal"] is True
        assert len(advisory["proposed_transfers"]) == 1
        assert advisory["proposed_transfers"][0]["out"] == "Player_13"


def test_missing_api_key_raises_error_for_gemini_and_openai(advisor_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = advisor_test_env

    # Gemini without key
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="Gemini API key is required"):
            generate_llm_advisory(
                gameweek=1,
                squad_path=squad_path,
                database_path=db_path,
                provider="gemini",
                api_key=None,
                save_reports=False,
            )

    # OpenAI without key
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="OpenAI API key is required"):
            generate_llm_advisory(
                gameweek=1,
                squad_path=squad_path,
                database_path=db_path,
                provider="openai",
                api_key=None,
                save_reports=False,
            )


def test_provider_openai_and_ollama_mocked(advisor_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = advisor_test_env

    mock_response = """
    Tactical breakdown:
    ```json
    {
      "critique_points": ["Rotation risk for mid"],
      "tactical_notes": ["Direct winger matchups"],
      "captain": "Player_2",
      "vice_captain": "Player_1",
      "transfers": []
    }
    ```
    """

    # OpenAI
    with patch("fpl_manager.llm_advisor._call_openai_api", return_value=mock_response):
        advisory_openai = generate_llm_advisory(
            gameweek=1,
            squad_path=squad_path,
            database_path=db_path,
            provider="openai",
            api_key="fake-openai-key",
            save_reports=False,
        )
        assert advisory_openai["provider_used"] == "openai"
        assert advisory_openai["proposed_captain"] == "Player_2"
        assert "Rotation risk for mid" in advisory_openai["critique_points"]

    # Ollama
    with patch("fpl_manager.llm_advisor._call_ollama_api", return_value=mock_response):
        advisory_ollama = generate_llm_advisory(
            gameweek=1,
            squad_path=squad_path,
            database_path=db_path,
            provider="ollama",
            save_reports=False,
        )
        assert advisory_ollama["provider_used"] == "ollama"
        assert advisory_ollama["proposed_captain"] == "Player_2"


def test_provider_auto_fallback_when_no_keys(advisor_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = advisor_test_env

    with patch.dict("os.environ", {}, clear=True):
        advisory_auto = generate_llm_advisory(
            gameweek=1,
            squad_path=squad_path,
            database_path=db_path,
            provider="auto",
            save_reports=False,
        )
        assert advisory_auto["provider_used"] == "heuristic (auto-fallback)"
        assert any("offline" in note.lower() for note in advisory_auto["tactical_notes"])


def test_unknown_provider_raises_error(advisor_test_env: tuple[Path, Path]) -> None:
    db_path, squad_path = advisor_test_env

    with pytest.raises(ValueError, match="Unknown provider 'unsupported_engine'"):
        generate_llm_advisory(
            gameweek=1,
            squad_path=squad_path,
            database_path=db_path,
            provider="unsupported_engine",
            save_reports=False,
        )
