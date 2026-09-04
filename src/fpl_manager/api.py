"""Minimal client for public, official Fantasy Premier League endpoints."""

import json
from typing import Any
from urllib.request import Request, urlopen


BASE_URL = "https://fantasy.premierleague.com/api"


def get_json(endpoint: str, timeout_seconds: int = 30) -> Any:
    request = Request(f"{BASE_URL}/{endpoint.lstrip('/')}", headers={"User-Agent": "fpl-manager/0.1"})
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.load(response)


def fetch_current_data() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return get_json("bootstrap-static/"), get_json("fixtures/")


def fetch_gameweek_live_data(event_id: int) -> dict[str, Any]:
    """Fetch live player performance and points for a specific gameweek."""
    return get_json(f"event/{event_id}/live/")

