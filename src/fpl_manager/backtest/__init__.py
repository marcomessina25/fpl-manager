"""Backtesting and evaluation subsystem for FPL Manager V0.7."""

from .engine import SimulationResult, run_decision_backtest, run_sequential_simulation
from .metrics import PredictionEvaluationRecord, evaluate_predictions, run_prediction_backtest
from .reporting import (
    build_backtest_report_path,
    format_decision_report,
    format_prediction_report,
    save_backtest_report,
)

__all__ = [
    "PredictionEvaluationRecord",
    "SimulationResult",
    "build_backtest_report_path",
    "evaluate_predictions",
    "format_decision_report",
    "format_prediction_report",
    "run_decision_backtest",
    "run_prediction_backtest",
    "run_sequential_simulation",
    "save_backtest_report",
]

