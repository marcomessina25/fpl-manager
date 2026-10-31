"""Multi-team management and team workspace isolation."""

import json
import re
from datetime import datetime, timezone
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

from .squad_state import CurrentSquadState, OwnershipSnapshot, live_command, load_current_squad, save_current_squad
from .application.files import delete_state_file, read_state_text, state_file_exists, write_state_text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
TEAMS_DIR = CONFIG_DIR / "teams"
DEFAULT_SQUAD_PATH = CONFIG_DIR / "current_squad.json"
EXAMPLE_SQUAD_PATH = CONFIG_DIR / "current_squad.example.json"
ACTIVE_TEAM_PATH = CONFIG_DIR / "active_team.json"


class TeamIDCollision(ValueError):
    """An authoritative team ID was occupied when the locked create began."""


def slugify_team_id(name: str) -> str:
    """Convert a human team name into a clean filesystem and identifier slug."""
    slug = re.sub(r"[^\w\s-]", "", name.strip().lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    if not slug:
        return "team"
    return slug


def team_workspace_exists(team_id: str, config_dir: Path | None = None) -> bool:
    """Reserve an ID only for authoritative files, including ambient staged state."""
    config_dir = config_dir or CONFIG_DIR
    workspace = config_dir / "teams" / team_id
    return (
        state_file_exists(workspace / "squad.json")
        or state_file_exists(workspace / "metadata.json")
        or (team_id == "default" and state_file_exists(config_dir / "current_squad.json"))
    )


def ensure_teams_initialized(config_dir: Path | None = None) -> None:
    """Ensure the teams directory and default team are initialized from current_squad.json."""
    config_dir = config_dir or CONFIG_DIR
    get_active_team_id(config_dir)
    teams_dir = config_dir / "teams"
    teams_dir.mkdir(parents=True, exist_ok=True)

    default_team_dir = teams_dir / "default"
    default_squad_file = default_team_dir / "squad.json"
    default_meta_file = default_team_dir / "metadata.json"
    legacy_squad_file = config_dir / "current_squad.json"

    # If default team squad does not exist, migrate or initialize it
    if not state_file_exists(default_squad_file):
        source = None
        if state_file_exists(legacy_squad_file):
            source = legacy_squad_file
        elif state_file_exists(config_dir / "current_squad.example.json"):
            source = config_dir / "current_squad.example.json"
        if source is not None:
            try:
                state = load_current_squad(source)
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(
                    f"Cannot initialize teams from '{source}': invalid squad state ({error}). "
                    "Repair the source squad file before initializing teams."
                ) from error
            default_team_dir.mkdir(parents=True, exist_ok=True)
            save_current_squad(default_squad_file, state)

    if state_file_exists(default_squad_file) and not state_file_exists(default_meta_file):
        meta = {
            "team_id": "default",
            "name": "Default Team",
            "manager": "Manager",
            "fpl_team_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        write_state_text(default_meta_file, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    active_file = config_dir / "active_team.json"
    if not state_file_exists(active_file):
        write_state_text(active_file, json.dumps({"active_team_id": "default"}, indent=2) + "\n")


def get_active_team_id(config_dir: Path | None = None) -> str:
    """Return the currently selected active team ID."""
    config_dir = config_dir or CONFIG_DIR
    active_file = config_dir / "active_team.json"
    if state_file_exists(active_file):
        try:
            data = json.loads(read_state_text(active_file))
        except ValueError as error:
            raise ValueError(
                f"Invalid active team file '{active_file}': {error}. "
                "Repair its JSON and active_team_id before selecting a team."
            ) from error
        tid = data.get("active_team_id") if isinstance(data, dict) else None
        if (
            not isinstance(tid, str) or not tid.strip() or tid != tid.strip()
            or tid in {".", ".."} or any(character in tid for character in "/\\:\0")
        ):
            raise ValueError(
                f"Invalid active team file '{active_file}': active_team_id must be a nonempty team ID, not a path. "
                "Repair the active_team_id before selecting a team."
            )
        return tid
    return "default"


@live_command("set_active_team")
def set_active_team(
    team_id: str,
    config_dir: Path | None = None,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Switch the global active team pointer to the specified team ID."""
    config_dir = config_dir or CONFIG_DIR
    ensure_teams_initialized(config_dir)
    teams = list_teams(config_dir)
    matching = [t for t in teams if t["team_id"] == team_id]
    if not matching:
        raise ValueError(f"Team '{team_id}' does not exist. Available teams: {', '.join(t['team_id'] for t in teams)}")

    active_file = config_dir / "active_team.json"
    write_state_text(active_file, json.dumps({"active_team_id": team_id}, indent=2) + "\n")
    team_meta = matching[0]
    team_meta["is_active"] = True
    return team_meta


def get_team_squad_path(team_id: str | None = None, config_dir: Path | None = None) -> Path:
    """Return the squad.json path for a given team ID or the active team."""
    config_dir = config_dir or CONFIG_DIR
    target_id = team_id or get_active_team_id(config_dir)

    team_dir = config_dir / "teams" / target_id
    team_squad = team_dir / "squad.json"
    if state_file_exists(team_squad):
        return team_squad

    legacy_squad = config_dir / "current_squad.json"
    if target_id == "default" and state_file_exists(legacy_squad):
        return legacy_squad

    return team_squad


def get_active_squad_path(config_dir: Path | None = None) -> Path:
    """Convenience shortcut returning the squad.json path for the active team."""
    return get_team_squad_path(None, config_dir)


def get_team_id_from_squad_path(squad_path: Path, config_dir: Path | None = None) -> str:
    """Identify which team ID a given squad path corresponds to."""
    config_dir = config_dir or CONFIG_DIR
    resolved = squad_path.resolve()
    if resolved.name == "squad.json" and resolved.parent.parent.name == "teams":
        return resolved.parent.name
    if resolved.name == "current_squad.json":
        return "default"
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


def resolve_creation_squad(
    squad_state: CurrentSquadState | None,
    copy_from_team_id: str | None,
    config_dir: Path | None = None,
) -> CurrentSquadState:
    """Resolve the creation source once, independently of the new team's target."""
    config_dir = config_dir or CONFIG_DIR
    if squad_state is not None:
        return squad_state
    if copy_from_team_id:
        copy_path = get_team_squad_path(copy_from_team_id, config_dir)
        if not state_file_exists(copy_path):
            raise ValueError(f"Team to copy from '{copy_from_team_id}' not found.")
        return load_current_squad(copy_path)
    active_path = get_active_squad_path(config_dir)
    if state_file_exists(active_path):
        return load_current_squad(active_path)
    example = config_dir / "current_squad.example.json"
    if state_file_exists(example):
        return load_current_squad(example)
    raise RuntimeError("No template squad available to initialize new team.")


@live_command("create_team")
def create_team(
    name: str,
    team_id: str | None = None,
    squad_state: CurrentSquadState | None = None,
    manager: str = "",
    fpl_team_id: int | None = None,
    copy_from_team_id: str | None = None,
    config_dir: Path | None = None,
    set_as_active: bool = True,
    database_path: Path | None = None,
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
        if team_workspace_exists(tid, config_dir):
            raise TeamIDCollision(f"Team '{tid}' already exists.")
    else:
        base_tid = slugify_team_id(clean_name)
        tid = base_tid
        counter = 2
        while team_workspace_exists(tid, config_dir):
            tid = f"{base_tid}-{counter}"
            counter += 1

    initial_squad = resolve_creation_squad(squad_state, copy_from_team_id, config_dir)

    team_dir = teams_dir / tid
    team_dir.mkdir(parents=True, exist_ok=True)
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
    write_state_text(meta_file, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    if set_as_active:
        set_active_team(tid, config_dir, database_path=database_path)

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
    """Compatibility read; advancing ownership state requires advance_current_squad."""
    return load_current_squad(squad_file)


@live_command("advance_current_squad")
def advance_current_squad(
    squad_path: Path,
    target_gameweek: int | None = None,
    team_id: str | None = None,
    config_dir: Path | None = None,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Explicitly advance GW/FT and renew each segment's chip inventory exactly once."""
    from .decision_log import compute_expected_free_transfers, normalize_chip
    from .storage import SnapshotStore
    state = load_current_squad(squad_path)
    team_id = team_id or get_team_id_from_squad_path(squad_path, config_dir)
    config_dir = config_dir or CONFIG_DIR
    database_path = database_path or config_dir.parent / "data" / "fpl.sqlite3"
    if target_gameweek is None:
        from .fixtures import get_current_gameweek
        store = SnapshotStore(database_path)
        store.initialize()
        target_gameweek = get_current_gameweek(store)
    if type(target_gameweek) is not int or not 1 <= target_gameweek <= 38:
        raise ValueError("Target gameweek must be an integer between 1 and 38.")
    if target_gameweek < (state.gameweek or 1):
        raise ValueError("Cannot advance a squad backwards.")
    if target_gameweek > (state.gameweek or 1) and state.pre_free_hit_state is None:
        store = SnapshotStore(database_path)
        store.initialize()
        with closing(store._connect()) as connection:
            row = connection.execute(
                "SELECT chip_played FROM decisions WHERE team_id = ? AND season = ? AND gameweek = ?",
                (team_id, state.season, state.gameweek or 1),
            ).fetchone()
        if row and row[0] and normalize_chip(row[0]) == "free_hit":
            raise ValueError("Legacy Free Hit has no authoritative pre-chip ownership snapshot; reconcile before advancing.")
    segment = 1 if target_gameweek <= 19 else 2
    previous_segment = state.chip_segment
    if previous_segment is None:
        if (state.gameweek or 1) <= 19:
            previous_segment = 1
        elif any(normalize_chip(chip) == "wildcard_2" for chip in state.chips_remaining):
            previous_segment = 2
        else:
            raise ValueError(
                "Legacy GW20+ chip inventory is ambiguous; reconcile recorded chip usage "
                "and explicitly migrate chip_segment before advancing."
            )
    chips = state.chips_remaining
    if segment > previous_segment:
        chips = ("wildcard_2", "free_hit", "bench_boost", "triple_captain")
        store = SnapshotStore(database_path)
        store.initialize()
        with closing(store._connect()) as connection:
            used = connection.execute(
                "SELECT chip_played FROM decisions WHERE team_id = ? AND season = ? "
                "AND gameweek BETWEEN 20 AND ? AND chip_played IS NOT NULL",
                (team_id, state.season, target_gameweek),
            ).fetchall()
        used_names = {normalize_chip(row[0]) for row in used}
        if "wildcard" in used_names:
            used_names.add("wildcard_2")
        chips = tuple(chip for chip in chips if normalize_chip(chip) not in used_names)
    changed = target_gameweek != state.gameweek or state.chip_segment != segment
    if changed:
        if state.pre_free_hit_state is not None and target_gameweek > state.pre_free_hit_state.gameweek:
            state = replace(state.pre_free_hit_state.restore(state), pre_free_hit_state=None)
        updated = replace(
            state, gameweek=target_gameweek, chip_segment=segment,
            chips_remaining=chips,
            free_transfers=compute_expected_free_transfers(
                target_gameweek, team_id=team_id, season=state.season, database_path=database_path
            ) if target_gameweek != state.gameweek else state.free_transfers,
        )
        if target_gameweek != state.gameweek:
            updated = replace(
                updated, gameweek_start_state=OwnershipSnapshot.capture(updated, target_gameweek),
            )
        save_current_squad(squad_path, updated)
    else:
        updated = state
    return {
        "team_id": team_id, "gameweek": updated.gameweek,
        "bank_tenths": updated.bank_tenths, "free_transfers": updated.free_transfers,
        "chips_remaining": list(updated.chips_remaining), "chip_segment": updated.chip_segment,
        "advanced": changed,
    }


def list_teams(config_dir: Path | None = None, database_path: Path | None = None) -> list[dict[str, Any]]:
    """List all configured teams, their metadata, squad summaries, and active status."""
    config_dir = config_dir or CONFIG_DIR
    teams_dir = config_dir / "teams"
    active_id = get_active_team_id(config_dir)

    results = []
    seen_ids = set()

    # Search config/teams/*
    if teams_dir.exists():
        for item in sorted(teams_dir.iterdir(), key=lambda p: p.name.lower()):
            if item.is_dir() and state_file_exists(item / "squad.json"):
                tid = item.name
                meta_file = item / "metadata.json"
                if state_file_exists(meta_file):
                    try:
                        meta = json.loads(read_state_text(meta_file))
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
    if "default" not in seen_ids and state_file_exists(legacy_squad):
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


@live_command("delete_team")
def delete_team(
    team_id: str,
    config_dir: Path | None = None,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Journal deletion of team files and reset the active pointer if needed."""
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
    delete_state_file(team_dir / "squad.json")
    delete_state_file(team_dir / "metadata.json")
    if team_dir.exists():
        for path in team_dir.rglob("*"):
            if path.is_file() and path not in {team_dir / "squad.json", team_dir / "metadata.json"}:
                delete_state_file(path)

    # If the active team was deleted, switch to the first remaining team
    active_id = get_active_team_id(config_dir)
    remaining_teams = list_teams(config_dir)
    new_active = active_id
    if active_id == team_id and remaining_teams:
        new_active = remaining_teams[0]["team_id"]
        write_state_text(
            config_dir / "active_team.json",
            json.dumps({"active_team_id": new_active}, indent=2) + "\n",
        )

    return {
        "deleted_team_id": team_id,
        "active_team_id": new_active,
    }


@live_command("rename_team")
def rename_team(
    team_id: str,
    new_name: str,
    config_dir: Path | None = None,
    database_path: Path | None = None,
) -> dict[str, Any]:
    """Change the display name of an existing team in its metadata."""
    clean_name = new_name.strip()
    if not clean_name:
        raise ValueError("Team name cannot be empty.")

    config_dir = config_dir or CONFIG_DIR
    ensure_teams_initialized(config_dir)
    teams_dir = config_dir / "teams"
    team_dir = teams_dir / team_id
    if not team_workspace_exists(team_id, config_dir):
        raise ValueError(f"Team '{team_id}' not found.")

    meta_file = team_dir / "metadata.json"
    if state_file_exists(meta_file):
        try:
            meta = json.loads(read_state_text(meta_file))
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
    write_state_text(meta_file, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")

    active_id = get_active_team_id(config_dir)
    meta["is_active"] = (team_id == active_id)
    return meta
