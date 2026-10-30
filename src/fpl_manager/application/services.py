"""Application commands and queries shared by HTTP, CLI and future clients."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .commands import CommandBus
from .contexts import CommandContext, HistoricalContext, LiveContext
from .errors import InvalidCommandError, StaleRevisionError
from .journal import CommandReceipt
from .read_models import ReadModel, StateIdentity, build_read_model

if TYPE_CHECKING:
    from ..simulation import HistoricalSimulationSession


class ApplicationService:
    def __init__(
        self, database_path: Path, config_dir: Path, *, season: str = "2026/27",
        historical_dir: Path | None = None,
    ) -> None:
        self.database_path = database_path
        self.config_dir = config_dir
        self.season = season
        self.historical_dir = historical_dir
        self.commands = CommandBus(
            database_path,
            historical_database_path=config_dir / "simulations" / "command_journal.sqlite3",
        )

    def historical_session(self, session_id: str) -> "HistoricalSimulationSession":
        from ..simulation import HistoricalSimulationSession

        # Validate before resolving a user-supplied ID into a file path.
        HistoricalContext(session_id, self.season, 1)
        return HistoricalSimulationSession.load(
            session_id, config_dir=self.config_dir / "simulations",
            historical_dir=self.historical_dir,
        )

    def historical_context(self, session_id: str) -> HistoricalContext:
        session = self.historical_session(session_id)
        return HistoricalContext(session.session_id, session.season, session.current_gw)

    def live_context(self, team_id: str) -> LiveContext:
        from ..squad_state import load_current_squad
        from ..teams import get_team_squad_path

        LiveContext(team_id, self.season, 1)
        state = load_current_squad(get_team_squad_path(team_id, self.config_dir))
        return LiveContext(team_id, state.season, state.gameweek or 1)

    def identity(self, context: CommandContext) -> StateIdentity:
        from ..execution import CURRENT_EXECUTION_VERSION

        if isinstance(context, HistoricalContext):
            session = self.historical_session(context.session_id)
            version, read_only = session.execution_version.value, session.read_only
        else:
            version, read_only = CURRENT_EXECUTION_VERSION.value, False
        return StateIdentity(context, self.commands.revision(context), version, read_only)

    def execute(
        self, context: CommandContext, operation: str, payload: dict[str, Any],
        action: Callable[[], Any], *, expected_revision: int | None = None,
        command_id: str | None = None,
    ) -> CommandReceipt:
        return self.commands.execute(
            context, operation, payload, action,
            expected_revision=expected_revision, command_id=command_id,
        )

    def query(
        self, context: CommandContext, operation: str, calculate: Callable[[], dict[str, Any]],
    ) -> ReadModel:
        before = self.identity(context)
        current = self.historical_context(context.session_id) if isinstance(context, HistoricalContext) else self.live_context(context.team_id)
        if current.to_dict() != context.to_dict():
            raise InvalidCommandError("The query deadline changed; refresh the selected state.")
        data = calculate()
        after = self.identity(context)
        if before.revision != after.revision:
            raise StaleRevisionError(context.to_dict(), before.revision, after.revision)
        return build_read_model(after, operation, data)

    def historical_command(
        self, context: HistoricalContext, operation: str, payload: dict[str, Any],
        *, expected_revision: int | None = None, command_id: str | None = None,
    ) -> CommandReceipt:
        def action() -> Any:
            session = self.historical_session(context.session_id)
            session.require_writable()
            if (session.season, session.current_gw) != (context.season, context.gameweek):
                raise InvalidCommandError("The simulation deadline changed; reload it before applying this command.")
            if operation == "transfers":
                return session.stage_transfers_batch(payload["transfers"])
            if operation == "clear-transfers":
                session.clear_staged_transfers()
                return {"success": True}
            if operation == "lineup":
                session.set_lineup(
                    payload["starting_ids"], payload["bench_ids"],
                    payload["captain_id"], payload["vice_captain_id"],
                )
                return {"success": True}
            if operation == "chip":
                chip = session.play_chip(payload["chip"]) if payload.get("chip") else session.cancel_chip()
                return {"active_chip": chip}
            if operation == "run-gw":
                return session.run_gameweek()
            if operation == "undo":
                return session.undo_last_gameweek()
            raise InvalidCommandError(f"Unknown historical command '{operation}'.")

        return self.execute(
            context, operation, payload, action,
            expected_revision=expected_revision, command_id=command_id,
        )

    def fork_historical(
        self, source_id: str, target_id: str, *, expected_revision: int | None = None,
        command_id: str | None = None,
    ) -> CommandReceipt:
        source = self.historical_session(source_id)
        context = HistoricalContext(target_id, source.season, source.current_gw)

        def action() -> dict[str, Any]:
            fork = source.fork_corrected(target_id)
            return {"session_id": fork.session_id, "season": fork.season, "current_gw": fork.current_gw}

        return self.execute(
            context, "fork", {"source_id": source_id, "target_id": target_id}, action,
            expected_revision=expected_revision, command_id=command_id,
        )

    def apply_live_plan_step(
        self, context: LiveContext, payload: dict[str, Any],
        *, expected_revision: int | None = None, command_id: str | None = None,
    ) -> CommandReceipt:
        from ..decision_log import log_decision_from_current_squad
        from ..teams import get_team_squad_path
        from ..transfers import execute_transfers

        def action() -> dict[str, Any]:
            squad_path = get_team_squad_path(context.team_id, self.config_dir)
            gameweek = int(payload.get("gameweek") or context.gameweek)
            starters = payload.get("starting_ids")
            bench = payload.get("bench_ids")
            captain = payload.get("captain_id")
            vice = payload.get("vice_captain_id")
            if starters is not None and len(starters) != 11:
                raise ValueError(f"Expected 11 starters, got {len(starters)}.")
            if bench is not None and len(bench) != 4:
                raise ValueError(f"Expected 4 bench players, got {len(bench)}.")
            if captain is not None and captain == vice:
                raise ValueError("Captain and Vice-Captain must be distinct players.")
            if starters is not None:
                if captain is not None and captain not in starters:
                    raise ValueError(f"Captain ID {captain} must be in starting XI.")
                if vice is not None and vice not in starters:
                    raise ValueError(f"Vice-Captain ID {vice} must be in starting XI.")
            transfers = [
                {
                    "outgoing_id": int(item.get("outgoing_id", item.get("out_id"))),
                    "incoming_id": int(item.get("incoming_id", item.get("in_id"))),
                }
                for item in (payload.get("transfers") or [])
            ]
            executed = execute_transfers(
                squad_path=squad_path, transfers=transfers,
                database_path=self.database_path, gameweek=gameweek,
            ) if transfers else None
            decision = log_decision_from_current_squad(
                gameweek=gameweek, squad_path=squad_path, database_path=self.database_path,
                team_id=context.team_id, season=context.season,
                starting_player_ids=payload.get("starting_ids"),
                bench_player_ids=payload.get("bench_ids"),
                captain_id=payload.get("captain_id", payload.get("captain")),
                vice_captain_id=payload.get("vice_captain_id", payload.get("vice_captain")),
                notes=payload.get("notes") or f"Applied from Multi-GW Planner (Step 0, GW{gameweek})",
            )
            return {
                "success": True, "team_id": context.team_id, "gameweek": gameweek,
                "transfers": executed.get("transfers", []) if executed else [], "decision": decision,
            }

        return self.execute(
            context, "apply-plan-step", payload, action,
            expected_revision=expected_revision, command_id=command_id,
        )

    def log_live_decision(
        self, context: LiveContext, payload: dict[str, Any], *, squad_path: Path | None = None,
        expected_revision: int | None = None, command_id: str | None = None,
    ) -> CommandReceipt:
        from ..decision_log import (
            get_gameweek_decision, log_decision_from_current_squad, record_actual_gameweek_score,
        )
        from ..teams import get_team_squad_path

        path = squad_path or get_team_squad_path(context.team_id, self.config_dir)

        def action() -> Any:
            gameweek = int(payload.get("gameweek") or context.gameweek)
            actual_points = payload.get("actual_points")
            existing = get_gameweek_decision(
                gameweek, season=context.season, team_id=context.team_id, database_path=self.database_path,
            )
            if actual_points is not None and existing is not None and not payload.get("overwrite", True):
                return record_actual_gameweek_score(
                    gameweek, actual_points, season=context.season,
                    team_id=context.team_id, database_path=self.database_path,
                )
            result = log_decision_from_current_squad(
                gameweek=gameweek, squad_path=path, database_path=self.database_path,
                team_id=context.team_id, season=context.season,
                squad_player_ids=payload.get("squad_players"),
                starting_player_ids=payload.get("starters"), bench_player_ids=payload.get("bench"),
                captain_id=payload.get("captain"), vice_captain_id=payload.get("vice_captain"),
                chip_played=payload.get("chip"), transfer_hits=payload.get("hits"),
                transfers=payload.get("transfers"), notes=payload.get("notes", ""),
                overwrite=payload.get("overwrite", True),
            )
            if actual_points is not None:
                result = record_actual_gameweek_score(
                    gameweek, actual_points, season=context.season,
                    team_id=context.team_id, database_path=self.database_path,
                )
            return result

        return self.execute(
            context, "log-decision", {"decision": payload, "squad_path": str(path.resolve())}, action,
            expected_revision=expected_revision, command_id=command_id,
        )

    def recover(self) -> list[CommandReceipt]:
        receipts = self.commands.recover()
        historical = self.config_dir / "simulations" / "command_journal.sqlite3"
        receipts.extend(CommandBus(historical, historical_database_path=historical).recover())
        return receipts
