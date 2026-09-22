"""Machine-readable experiment manifest definitions and generation (P1).

Provides an unambiguous specification of every ablation variant across all
10 scientific dimensions, ensuring complete reproducibility without reading code.
"""

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ComponentSpecification:
    """Specification of an isolated experiment component configuration."""
    variant_id: str
    description: str
    input_data: str
    predictor_implementation: str
    participation_implementation: str
    calibration_implementation: str
    xp_components_implementation: str
    regimes_enabled: bool
    calibration_enabled: bool
    default_decision_engine: str
    optimizer_function: str
    objective_function: str
    transfer_policy: str
    captain_policy: str
    hidden_defaults: dict[str, Any] = field(default_factory=dict)


def build_ablation_manifest() -> dict[str, Any]:
    """Construct the complete machine-readable manifest of all supported ablation variants."""
    common_defaults = {
        "budget_limit_tenths": 1000,
        "max_club_players": 3,
        "min_free_transfers": 1,
        "max_accumulated_free_transfers": 5,
        "point_in_time_guarantee": "Pre-deadline snapshot isolation",
    }

    variants: dict[str, ComponentSpecification] = {
        "v0.8": ComponentSpecification(
            variant_id="v0.8",
            description="Frozen V0.8 Baseline: Heuristic participation rules with uncalibrated V0.8 xP components",
            input_data="HistoricalGameweekSnapshot (data/historical/<season>/gw<gw>.json)",
            predictor_implementation="fpl_manager.expected_points.project_player_gameweek(predictor_version='v0.8')",
            participation_implementation="fpl_manager.expected_points.calculate_expected_minutes",
            calibration_implementation="None (Uncalibrated heuristic)",
            xp_components_implementation="fpl_manager.expected_points (v0.8 components)",
            regimes_enabled=False,
            calibration_enabled=False,
            default_decision_engine="DecisionEngineV08 (fpl_manager.backtest.decision_engine.DecisionEngineV08)",
            optimizer_function="fpl_manager.optimizer.solve_transfers (unconstrained)",
            objective_function="score = xp_delta - hit_cost (pure expected points)",
            transfer_policy="Greedy branch-and-bound evaluating raw xP gains",
            captain_policy="Highest raw predicted expected points among starters",
            hidden_defaults=common_defaults,
        ),
        "v0.9": ComponentSpecification(
            variant_id="v0.9",
            description="Full V0.9 Pipeline: Learned hierarchical participation, rotation regimes, probability calibration, and recalibrated components",
            input_data="HistoricalGameweekSnapshot (data/historical/<season>/gw<gw>.json)",
            predictor_implementation="fpl_manager.expected_points.project_player_gameweek(predictor_version='v0.9')",
            participation_implementation="fpl_manager.learned_participation.predict_player_participation_v09",
            calibration_implementation="fpl_manager.calibration (Isotonic regression / Platt scaling)",
            xp_components_implementation="fpl_manager.expected_points (v0.9 components)",
            regimes_enabled=True,
            calibration_enabled=True,
            default_decision_engine="DecisionEngineV09 (fpl_manager.backtest.decision_engine.DecisionEngineV09)",
            optimizer_function="fpl_manager.optimizer.solve_transfers (participation-aware)",
            objective_function="score = (xp_in * (0.85 + 0.15 * p_start) - xp_out) - hit_cost",
            transfer_policy="Rotation-aware transfer search filtering out candidates with P(start) < 0.30",
            captain_policy="Participation safeguard requiring P(start) >= 0.60 for captain candidate selection",
            hidden_defaults=common_defaults,
        ),
        "v0.9_part_v0.8_comp": ComponentSpecification(
            variant_id="v0.9_part_v0.8_comp",
            description="V0.9 Learned Participation + Frozen V0.8 xP Components (Isolates participation model gains)",
            input_data="HistoricalGameweekSnapshot (data/historical/<season>/gw<gw>.json)",
            predictor_implementation="fpl_manager.expected_points.project_player_gameweek(predictor_version='v0.9_part_v0.8_comp')",
            participation_implementation="fpl_manager.learned_participation.predict_player_participation_v09",
            calibration_implementation="fpl_manager.calibration (Isotonic regression / Platt scaling)",
            xp_components_implementation="fpl_manager.expected_points (v0.8 components)",
            regimes_enabled=True,
            calibration_enabled=True,
            default_decision_engine="DecisionEngineV09",
            optimizer_function="fpl_manager.optimizer.solve_transfers (participation-aware)",
            objective_function="score = (xp_in * (0.85 + 0.15 * p_start) - xp_out) - hit_cost",
            transfer_policy="Rotation-aware transfer search filtering out candidates with P(start) < 0.30",
            captain_policy="Participation safeguard requiring P(start) >= 0.60 for captain candidate selection",
            hidden_defaults=common_defaults,
        ),
        "v0.8_part_v0.9_comp": ComponentSpecification(
            variant_id="v0.8_part_v0.9_comp",
            description="V0.8 Heuristic Participation + V0.9 xP Components (Isolates component recalibration effect)",
            input_data="HistoricalGameweekSnapshot (data/historical/<season>/gw<gw>.json)",
            predictor_implementation="fpl_manager.expected_points.project_player_gameweek(predictor_version='v0.8_part_v0.9_comp')",
            participation_implementation="fpl_manager.expected_points.calculate_expected_minutes",
            calibration_implementation="None (Uncalibrated)",
            xp_components_implementation="fpl_manager.expected_points (v0.9 components)",
            regimes_enabled=False,
            calibration_enabled=False,
            default_decision_engine="DecisionEngineV09",
            optimizer_function="fpl_manager.optimizer.solve_transfers",
            objective_function="score = xp_delta - hit_cost",
            transfer_policy="Standard optimizer search",
            captain_policy="Highest predicted xP among starters",
            hidden_defaults=common_defaults,
        ),
        "v0.9_no_regimes": ComponentSpecification(
            variant_id="v0.9_no_regimes",
            description="V0.9 Participation without Rotation Regimes (Ablates Phase 5 regime overlay)",
            input_data="HistoricalGameweekSnapshot (data/historical/<season>/gw<gw>.json)",
            predictor_implementation="fpl_manager.expected_points.project_player_gameweek(predictor_version='v0.9_no_regimes')",
            participation_implementation="fpl_manager.learned_participation.predict_player_participation_v09(use_regimes=False)",
            calibration_implementation="fpl_manager.calibration",
            xp_components_implementation="fpl_manager.expected_points (v0.9 components)",
            regimes_enabled=False,
            calibration_enabled=True,
            default_decision_engine="DecisionEngineV09",
            optimizer_function="fpl_manager.optimizer.solve_transfers",
            objective_function="Risk-adjusted expected points",
            transfer_policy="Standard rotation-aware search",
            captain_policy="Participation safeguard P(start) >= 0.60",
            hidden_defaults=common_defaults,
        ),
        "v0.9_no_calib": ComponentSpecification(
            variant_id="v0.9_no_calib",
            description="V0.9 Participation without Probability Calibration (Ablates Phase 4 calibration)",
            input_data="HistoricalGameweekSnapshot (data/historical/<season>/gw<gw>.json)",
            predictor_implementation="fpl_manager.expected_points.project_player_gameweek(predictor_version='v0.9_no_calib')",
            participation_implementation="fpl_manager.learned_participation.predict_player_participation_v09(use_calibration=False)",
            calibration_implementation="None",
            xp_components_implementation="fpl_manager.expected_points (v0.9 components)",
            regimes_enabled=True,
            calibration_enabled=False,
            default_decision_engine="DecisionEngineV09",
            optimizer_function="fpl_manager.optimizer.solve_transfers",
            objective_function="Risk-adjusted expected points",
            transfer_policy="Standard rotation-aware search",
            captain_policy="Participation safeguard P(start) >= 0.60",
            hidden_defaults=common_defaults,
        ),
        "v0.9_raw": ComponentSpecification(
            variant_id="v0.9_raw",
            description="V0.9 Raw Participation Model (No regimes and no calibration)",
            input_data="HistoricalGameweekSnapshot (data/historical/<season>/gw<gw>.json)",
            predictor_implementation="fpl_manager.expected_points.project_player_gameweek(predictor_version='v0.9_raw')",
            participation_implementation="fpl_manager.learned_participation.predict_player_participation_v09(use_regimes=False, use_calibration=False)",
            calibration_implementation="None",
            xp_components_implementation="fpl_manager.expected_points (v0.9 components)",
            regimes_enabled=False,
            calibration_enabled=False,
            default_decision_engine="DecisionEngineV09",
            optimizer_function="fpl_manager.optimizer.solve_transfers",
            objective_function="Risk-adjusted expected points",
            transfer_policy="Standard rotation-aware search",
            captain_policy="Participation safeguard P(start) >= 0.60",
            hidden_defaults=common_defaults,
        ),
        "v1.0": ComponentSpecification(
            variant_id="v1.0",
            description="V1.0 Production Baseline: Frozen V0.9.1 calibrated predictor with DecisionEngineV10 (lineup_penalty_weight = 0.0)",
            input_data="HistoricalGameweekSnapshot (data/historical/<season>/gw<gw>.json)",
            predictor_implementation="fpl_manager.expected_points.project_player_gameweek(predictor_version='v1.0')",
            participation_implementation="fpl_manager.learned_participation.predict_player_participation_v09",
            calibration_implementation="fpl_manager.calibration (Isotonic regression / Platt scaling)",
            xp_components_implementation="fpl_manager.expected_points (v0.9 components)",
            regimes_enabled=True,
            calibration_enabled=True,
            default_decision_engine="DecisionEngineV10 (lineup_penalty_weight = 0.0)",
            optimizer_function="fpl_manager.optimizer.solve_transfers (participation-aware)",
            objective_function="score = xp_in - xp_out - hit_cost (neutral lineup_penalty_weight = 0.0)",
            transfer_policy="Rotation-aware transfer search filtering out candidates with P(start) < 0.30",
            captain_policy="Participation safeguard requiring P(start) >= 0.60 for captain candidate selection",
            hidden_defaults={**common_defaults, "lineup_penalty_weight": 0.0},
        ),
    }

    manifest = {
        "schema_version": "1.0.0",
        "description": "FPL Manager Scientific Ablation Component Manifest (P1 Audit)",
        "generated_at": "2026-09-22T17:00:00Z",
        "variants": {k: asdict(v) for k, v in variants.items()},
        "decision_engines": {
            "v0.8": {
                "class": "fpl_manager.backtest.decision_engine.DecisionEngineV08",
                "name": "V0.8 Frozen Heuristic Decision Engine",
                "squad_initialization": "Greedy rank-by-position without club saturation swap fallback",
                "lineup_selection": "Sorted by raw (expected_points, base_xp); captain is max raw xP",
                "transfer_objective": "score = xp_delta - hit_cost (unconstrained)",
            },
            "v0.9": {
                "class": "fpl_manager.backtest.decision_engine.DecisionEngineV09",
                "name": "V0.9 Participation-Aware Decision Engine",
                "squad_initialization": "Saturation-swap enabled greedy selection with 3-player club cap resolution",
                "lineup_selection": "Starters ranked by calibrated xP (lineup_penalty_weight = 0.0); captain requires P(start) >= 0.60 safeguard",
                "transfer_objective": "score = (adj_xp_in - xp_out) - hit_cost with rotation-risk discount",
            },
            "v1.0": {
                "class": "fpl_manager.backtest.decision_engine.DecisionEngineV10",
                "name": "V1.0 Production Decision Engine (Neutral Calibrated xP, w=0.00)",
                "squad_initialization": "Saturation-swap enabled greedy selection with 3-player club cap resolution",
                "lineup_selection": "Starters ranked by calibrated expected_points (lineup_penalty_weight = 0.0); captain requires P(start) >= 0.60 safeguard",
                "transfer_objective": "score = (adj_xp_in - xp_out) - hit_cost with rotation-risk discount",
            },
        },
    }
    return manifest


def save_manifest(output_path: Path = Path("reports/experiment_manifest.json")) -> Path:
    """Serialize the experiment manifest to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_ablation_manifest()
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output_path
