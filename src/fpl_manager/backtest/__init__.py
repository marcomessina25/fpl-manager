"""Backtesting and evaluation subsystem for FPL Manager V0.7."""

from .metrics import PredictionEvaluationRecord, evaluate_predictions
from .reporting import format_prediction_report

__all__ = [
    "PredictionEvaluationRecord",
    "evaluate_predictions",
    "format_prediction_report",
]
