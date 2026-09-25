"""Multi-team management and team workspace isolation."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .squad_state import CurrentSquadState, load_current_squad, save_current_squad

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
TEAMS_DIR = CONFIG_DIR / "teams"
DEFAULT_SQUAD_PATH = CONFIG_DIR / "current_squad.json"
EXAMPLE_SQUAD_PATH = CONFIG_DIR / "current_squad.example.json"
ACTIVE_TEAM_PATH = CONFIG_DIR / "active_team.json"


def slugify_team_id(name: str) -> str:
    """Convert a human team name into a clean filesystem and identifier slug."""
    slug = re.sub(r"[^\w\s-]", "", name.strip().lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    if not slug:
        return "team"
    return slug


def ensure_teams_initialized(config_dir: Path | None = None) -> None:
    """Ensure the teams directory and default team are initialized from current_squad.json."""
    config_dir = config_dir or CONFIG_DIR
    teams_dir = config_dir / "teams"
    teams_dir.mkdir(parents=True, exist_ok=True)

    default_team_dir = teams_dir / "default"
    default_squad_file = default_team_dir / "squad.json"
    default_meta_file = default_team_dir / "metadata.json"
    legacy_squad_file = config_dir / "current_squad.json"

    # If default team squad does not exist, migrate or initialize it
    if not default_squad_file.exists():
        if legacy_squad_file.exists():
            try:
                state = load_current_squad(legacy_squad_file)
                default_team_dir.mkdir(parents=True, exist_ok=True)
                save_current_squad(default_squad_file, state)
            except Exception:
                pass
        elif (config_dir / "current_squad.example.json").exists():
            try:
                state = load_current_squad(config_dir / "current_squad.example.json")
                default_team_dir.mkdir(parents=True, exist_ok=True)
                save_current_squad(default_squad_file, state)
            except Exception:
                pass

    if default_squad_file.exists() and not default_meta_file.exists():
        meta = {
            "team_id": "default",
            "name": "Default Team",
            "manager": "Manager",
            "fpl_team_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        default_meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    active_file = config_dir / "active_team.json"
    if not active_file.exists():
        active_file.write_text(json.dumps({"active_team_id": "default"}, indent=2) + "\n", encoding="utf-8")


def get_active_team_id(config_dir: Path | None = None) -> str:
    """Return the currently selected active team ID."""
    config_dir = config_dir or CONFIG_DIR
    active_file = config_dir / "active_team.json"
    if active_file.exists():
        try:
            data = json.loads(active_file.read_text(encoding="utf-8"))
            tid = data.get("active_team_id")
            if tid:
                return str(tid)
        except Exception:
            pass
    return "default"


def set_active_team(team_id: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Switch the global active team pointer to the specified team ID."""
    config_dir = config_dir or CONFIG_DIR
    ensure_teams_initialized(config_dir)
    teams = list_teams(config_dir)
    matching = [t for t in teams if t["team_id"] == team_id]
    if not matching:
        raise ValueError(f"Team '{team_id}' does not exist. Available teams: {', '.join(t['team_id'] for t in teams)}")

    active_file = config_dir / "active_team.json"
    active_file.write_text(json.dumps({"active_team_id": team_id}, indent=2) + "\n", encoding="utf-8")
    team_meta = matching[0]
    team_meta["is_active"] = True
    return team_meta


def get_team_squad_path(team_id: str | None = None, config_dir: Path | None = None) -> Path:
    """Return the squad.json path for a given team ID or the active team."""
    config_dir = config_dir or CONFIG_DIR
    ensure_teams_initialized(config_dir)
    target_id = team_id or get_active_team_id(config_dir)

    team_dir = config_dir / "teams" / target_id
    team_squad = team_dir / "squad.json"
    if team_squad.exists():
        return team_squad

    legacy_squad = config_dir / "current_squad.json"
    if target_id == "default" and legacy_squad.exists():
        return legacy_squad

    return team_squad


def get_active_squad_path(config_dir: Path | None = None) -> Path:
    """Convenience shortcut returning the squad.json path for the active team."""
    return get_team_squad_path(None, config_dir)


def get_team_id_from_squad_path(squad_path: Path, config_dir: Path | None = None) -> str:
    """Identify which team ID a given squad path corresponds to."""
    config_dir = config_dir or CONFIG_DIR
    resolved = squad_path.resolve()
    teams_dir = (config_dir / "teams").resolve()

    try:
        rel = resolved.relative_to(teams_dir)
        parts = rel.parts
        if parts:
            return parts[0]
    except ValueError:
        pass

    if resolved == (config_dir / "current_squad.json").resolve():
        return "default"

    return get_active_team_id(config_dir)


def create_team(
    name: str,
    team_id: str | None = None,
    squad_state: CurrentSquadState | None = None,
    manager: str = "",
    fpl_team_id: int | None = None,
    copy_from_team_id: str | None = None,
    config_dir: Path | None = None,
    set_as_active: bool = True,
) -> dict[str, Any]:
    """Create a new isolated team with its own squad state and metadata."""
    if not name or not name.strip():
        raise ValueError("Team name cannot be empty.")

    config_dir = config_dir or CONFIG_DIR
    ensure_teams_initialized(config_dir)
    clean_name = name.strip()
    teams_dir = config_dir / "teams"

    if team_id:
        tid = slugify_team_id(team_id)
        if (teams_dir / tid).exists():
            raise ValueError(f"Team '{tid}' already exists.")
    else:
        base_tid = slugify_team_id(clean_name)
        tid = base_tid
        counter = 2
        while (teams_dir / tid).exists():
            tid = f"{base_tid}-{counter}"
            counter += 1

    team_dir = teams_dir / tid
    team_dir.mkdir(parents=True, exist_ok=True)

    # Determine initial squad state
    if squad_state is not None:
        initial_squad = squad_state
    elif copy_from_team_id:
        copy_path = get_team_squad_path(copy_from_team_id, config_dir)
        if not copy_path.exists():
            raise ValueError(f"Team to copy from '{copy_from_team_id}' not found.")
        initial_squad = load_current_squad(copy_path)
    else:
        active_path = get_active_squad_path(config_dir)
        if active_path.exists():
            initial_squad = load_current_squad(active_path)
        elif (config_dir / "current_squad.example.json").exists():
            initial_squad = load_current_squad(config_dir / "current_squad.example.json")
        else:
            raise RuntimeError("No template squad available to initialize new team.")

    squad_file = team_dir / "squad.json"
    save_current_squad(squad_file, initial_squad)

    meta = {
        "team_id": tid,
        "name": clean_name,
        "manager": manager.strip() or "Manager",
        "fpl_team_id": fpl_team_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_file = team_dir / "metadata.json"
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if set_as_active:
        set_active_team(tid, config_dir)

    result = dict(meta)
    result["squad_path"] = str(squad_file)
    result["gameweek"] = initial_squad.gameweek
    result["bank_tenths"] = initial_squad.bank_tenths
    result["free_transfers"] = initial_squad.free_transfers
    result["is_active"] = set_as_active
    return result


def sync_squad_with_current_gameweek(
    squad_file: Path,
    team_id: str = "default",
    config_dir: Path | None = None,
    database_path: Path | None = None,
) -> CurrentSquadState:
    """Check and synchronize squad state gameweek and free transfers with the database."""
    config_dir = config_dir or CONFIG_DIR
    state = load_current_squad(squad_file)
    db_path = database_path or (config_dir.parent / "data" / "fpl.sqlite3")
    if db_path.exists():
        try:
            from .storage import SnapshotStore
            from .fixtures import get_current_gameweek
            from .decision_log import compute_expected_free_transfers
            store = SnapshotStore(db_path)
            curr_gw = get_current_gameweek(store)
            if state.gameweek is None or state.gameweek < curr_gw:
                new_ft = compute_expected_free_transfers(curr_gw, team_id=team_id, season=state.season, database_path=db_path)
                updated_state = CurrentSquadState(
                    player_ids=state.player_ids,
                    purchase_prices_tenths=state.purchase_prices_tenths,
                    bank_tenths=state.bank_tenths,
                    free_transfers=new_ft,
                    chips_remaining=state.chips_remaining,
                    season=state.season,
                    gameweek=curr_gw,
                )
                save_current_squad(squad_file, updated_state)
                return updated_state
        except Exception:
            pass
    return state


def list_teams(config_dir: Path | None = None, database_path: Path | None = None) -> list[dict[str, Any]]:
    """List all configured teams, their metadata, squad summaries, and active status."""
    config_dir = config_dir or CONFIG_DIR
    ensure_teams_initialized(config_dir)
    teams_dir = config_dir / "teams"
    active_id = get_active_team_id(config_dir)

    results = []
    seen_ids = set()

    # Search config/teams/*
    if teams_dir.exists():
        for item in sorted(teams_dir.iterdir(), key=lambda p: p.name.lower()):
            if item.is_dir() and (item / "squad.json").exists():
                tid = item.name
                meta_file = item / "metadata.json"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    except Exception:
                        meta = {"team_id": tid, "name": tid.replace("-", " ").title()}
                else:
                    meta = {"team_id": tid, "name": tid.replace("-", " ").title()}

                try:
                    state = sync_squad_with_current_gameweek(
                        item / "squad.json",
                        team_id=tid,
                        config_dir=config_dir,
                        database_path=database_path,
                    )
                    bank = state.bank_tenths / 10.0
                    total_spent = sum(state.purchase_prices_tenths.values()) / 10.0
                    gw = state.gameweek
                    players_count = len(state.player_ids)
                    free_transfers = state.free_transfers
                except Exception:
                    bank = 0.0
                    total_spent = 0.0
                    gw = 1
                    players_count = 0
                    free_transfers = 1

                results.append({
                    "team_id": tid,
                    "name": meta.get("name", tid),
                    "manager": meta.get("manager", "Manager"),
                    "fpl_team_id": meta.get("fpl_team_id"),
                    "created_at": meta.get("created_at"),
                    "gameweek": gw,
                    "bank_millions": round(bank, 1),
                    "team_value_millions": round(total_spent + bank, 1),
                    "players_count": players_count,
                    "free_transfers": free_transfers,
                    "squad_path": str(item / "squad.json"),
                    "is_active": (tid == active_id),
                })
                seen_ids.add(tid)

    # Legacy fallback for default team if not in seen_ids
    legacy_squad = config_dir / "current_squad.json"
    if "default" not in seen_ids and legacy_squad.exists():
        try:
            state = sync_squad_with_current_gameweek(
                legacy_squad,
                team_id="default",
                config_dir=config_dir,
                database_path=database_path,
            )
            bank = state.bank_tenths / 10.0
            total_spent = sum(state.purchase_prices_tenths.values()) / 10.0
            results.insert(0, {
                "team_id": "default",
                "name": "Default Team",
                "manager": "Manager",
                "fpl_team_id": None,
                "created_at": None,
                "gameweek": state.gameweek,
                "bank_millions": round(bank, 1),
                "team_value_millions": round(total_spent + bank, 1),
                "players_count": len(state.player_ids),
                "free_transfers": state.free_transfers,
                "squad_path": str(legacy_squad),
                "is_active": (active_id == "default"),
            })
        except Exception:
            pass

    return results


def get_team(
    team_id: str | None = None,
    config_dir: Path | None = None,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Retrieve full team metadata and squad state for a given team ID or active team."""
    config_dir = config_dir or CONFIG_DIR
    ensure_teams_initialized(config_dir)
    target_id = team_id or get_active_team_id(config_dir)

    teams = list_teams(config_dir, database_path=database_path)
    matching = [t for t in teams if t["team_id"] == target_id]
    if not matching:
        raise ValueError(f"Team '{target_id}' not found.")

    team_data = matching[0]
    squad_path = Path(team_data["squad_path"])
    squad_state = sync_squad_with_current_gameweek(
        squad_path,
        team_id=target_id,
        config_dir=config_dir,
        database_path=database_path,
    )

    return {
        "metadata": team_data,
        "state": squad_state,
        "is_active": team_data["is_active"],
    }


def delete_team(team_id: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Delete a team directory and reset the active team if needed."""
    if team_id == "default":
        raise ValueError("Cannot delete the default team.")

    config_dir = config_dir or CONFIG_DIR
    ensure_teams_initialized(config_dir)
    teams = list_teams(config_dir)
    matching = [t for t in teams if t["team_id"] == team_id]
    if not matching:
        raise ValueError(f"Team '{team_id}' not found.")

    if len(teams) <= 1:
        raise ValueError("Cannot delete the only remaining team.")

    team_dir = config_dir / "teams" / team_id
    if team_dir.exists():
        import shutil
        shutil.rmtree(team_dir)

    # If the active team was deleted, switch to the first remaining team
    active_id = get_active_team_id(config_dir)
    remaining_teams = list_teams(config_dir)
    new_active = active_id
    if active_id == team_id and remaining_teams:
        new_active = remaining_teams[0]["team_id"]
        set_active_team(new_active, config_dir)

    return {
        "deleted_team_id": team_id,
        "active_team_id": new_active,
    }


def rename_team(team_id: str, new_name: str, config_dir: Path | None = None) -> dict[str, Any]:
    """Change the display name of an existing team in its metadata."""
    clean_name = new_name.strip()
    if not clean_name:
        raise ValueError("Team name cannot be empty.")

    config_dir = config_dir or CONFIG_DIR
    ensure_teams_initialized(config_dir)
    teams_dir = config_dir / "teams"
    team_dir = teams_dir / team_id
    if not team_dir.exists():
        raise ValueError(f"Team '{team_id}' not found.")

    meta_file = team_dir / "metadata.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            meta = {
                "team_id": team_id,
                "manager": "Manager",
                "fpl_team_id": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
    else:
        meta = {
            "team_id": team_id,
            "manager": "Manager",
            "fpl_team_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    meta["name"] = clean_name
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    active_id = get_active_team_id(config_dir)
    meta["is_active"] = (team_id == active_id)
    return meta
