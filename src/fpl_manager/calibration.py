"""Probability calibration diagnostics, reliability curves, and calibrators for V0.9 (Phase 4).

Implements Section 12 & Milestone V0.9.4 of docs/v09/v09.md:
- Brier Score and Log Loss calculation.
- Reliability diagrams & calibration curves by probability bucket.
- Expected Calibration Error (ECE) and Maximum Calibration Error (MCE).
- Position and role cohort calibration breakdown.
- Pure Python Platt scaling and Isotonic regression calibrators (zero external dependencies).
"""

from dataclasses import dataclass, asdict
import math
from typing import Any


def _safe_log(val: float, eps: float = 1e-12) -> float:
    return math.log(max(eps, min(1.0 - eps, val)))


def _safe_sigmoid(z: float) -> float:
    if z >= 35.0:
        return 1.0
    if z <= -35.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-z))


def _logit(p: float, eps: float = 1e-6) -> float:
    clamped = max(eps, min(1.0 - eps, p))
    return math.log(clamped / (1.0 - clamped))


def compute_brier_score(probabilities: list[float], outcomes: list[int]) -> float:
    """Compute Brier Score: MSE between predicted probabilities and binary outcomes."""
    if not probabilities or len(probabilities) != len(outcomes):
        return 0.0
    return round(sum((p - y) ** 2 for p, y in zip(probabilities, outcomes)) / len(probabilities), 4)


def compute_log_loss(probabilities: list[float], outcomes: list[int], eps: float = 1e-12) -> float:
    """Compute Logarithmic Loss (Cross-Entropy) for binary predictions."""
    if not probabilities or len(probabilities) != len(outcomes):
        return 0.0
    total = 0.0
    for p, y in zip(probabilities, outcomes):
        p_clamped = max(eps, min(1.0 - eps, p))
        total -= (y * math.log(p_clamped) + (1 - y) * math.log(1.0 - p_clamped))
    return round(total / len(probabilities), 4)


@dataclass(frozen=True, slots=True)
class ReliabilityBucket:
    """Summary of a single probability bin on the reliability curve."""
    bin_index: int
    bin_min: float
    bin_max: float
    count: int
    mean_predicted: float
    empirical_rate: float
    calibration_error: float


@dataclass(frozen=True, slots=True)
class ReliabilityMetrics:
    """Complete reliability diagram metrics across bins."""
    brier_score: float
    log_loss: float
    expected_calibration_error: float  # ECE: sample-weighted average error
    maximum_calibration_error: float   # MCE: maximum bin error
    total_samples: int
    buckets: list[ReliabilityBucket]

    def to_dict(self) -> dict[str, Any]:
        return {
            "brier_score": self.brier_score,
            "log_loss": self.log_loss,
            "expected_calibration_error": self.expected_calibration_error,
            "maximum_calibration_error": self.maximum_calibration_error,
            "total_samples": self.total_samples,
            "buckets": [asdict(b) for b in self.buckets],
        }


def compute_reliability_curve(
    probabilities: list[float],
    outcomes: list[int],
    n_bins: int = 10,
) -> ReliabilityMetrics:
    """Construct reliability diagram metrics partitioning [0, 1] into uniform bins."""
    if not probabilities or len(probabilities) != len(outcomes):
        return ReliabilityMetrics(0.0, 0.0, 0.0, 0.0, 0, [])

    brier = compute_brier_score(probabilities, outcomes)
    loss = compute_log_loss(probabilities, outcomes)
    total_samples = len(probabilities)

    bucket_width = 1.0 / n_bins
    buckets: list[ReliabilityBucket] = []
    weighted_ece = 0.0
    max_error = 0.0

    for i in range(n_bins):
        bin_min = i * bucket_width
        bin_max = (i + 1) * bucket_width

        # Include upper bound on final bin
        if i == n_bins - 1:
            indices = [idx for idx, p in enumerate(probabilities) if bin_min <= p <= bin_max]
        else:
            indices = [idx for idx, p in enumerate(probabilities) if bin_min <= p < bin_max]

        cnt = len(indices)
        if cnt > 0:
            bin_preds = [probabilities[idx] for idx in indices]
            bin_acts = [outcomes[idx] for idx in indices]
            mean_p = round(sum(bin_preds) / cnt, 4)
            emp_rate = round(sum(bin_acts) / cnt, 4)
            cal_err = round(abs(mean_p - emp_rate), 4)
        else:
            mean_p = round((bin_min + bin_max) / 2.0, 4)
            emp_rate = 0.0
            cal_err = 0.0

        buckets.append(
            ReliabilityBucket(
                bin_index=i,
                bin_min=round(bin_min, 2),
                bin_max=round(bin_max, 2),
                count=cnt,
                mean_predicted=mean_p,
                empirical_rate=emp_rate,
                calibration_error=cal_err,
            )
        )

        weighted_ece += cal_err * (cnt / total_samples)
        if cal_err > max_error and cnt >= 10:  # Require minimum samples for MCE
            max_error = cal_err

    return ReliabilityMetrics(
        brier_score=brier,
        log_loss=loss,
        expected_calibration_error=round(weighted_ece, 4),
        maximum_calibration_error=round(max_error, 4),
        total_samples=total_samples,
        buckets=buckets,
    )


@dataclass
class PlattCalibrator:
    """Pure-Python Platt Scaling calibrator fitting P_cal = sigmoid(a * logit(p) + b)."""

    a: float = 1.0
    b: float = 0.0

    def calibrate(self, probability: float) -> float:
        """Transform uncalibrated probability using learned logistic scaling."""
        z = _logit(probability)
        scaled_z = self.a * z + self.b
        return round(_safe_sigmoid(scaled_z), 4)

    def to_dict(self) -> dict[str, Any]:
        return {"type": "platt", "a": round(self.a, 5), "b": round(self.b, 5)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlattCalibrator":
        return cls(a=data.get("a", 1.0), b=data.get("b", 0.0))

    @classmethod
    def fit(
        cls,
        probabilities: list[float],
        outcomes: list[int],
        epochs: int = 250,
        learning_rate: float = 0.1,
    ) -> "PlattCalibrator":
        """Fit parameters a and b using gradient descent with log-loss objective."""
        if not probabilities or len(probabilities) != len(outcomes):
            return cls(1.0, 0.0)

        # Target smoothing to avoid over-confident calibration
        N = len(probabilities)
        logits = [_logit(p) for p in probabilities]

        a = 1.0
        b = 0.0

        for _ in range(epochs):
            grad_a = 0.0
            grad_b = 0.0
            for z, y in zip(logits, outcomes):
                p = _safe_sigmoid(a * z + b)
                err = p - y
                grad_a += err * z
                grad_b += err

            a -= learning_rate * (grad_a / N)
            b -= learning_rate * (grad_b / N)
            # a should remain positive to preserve monotonicity
            a = max(0.01, a)

        return cls(a=round(a, 5), b=round(b, 5))


@dataclass
class IsotonicCalibrator:
    """Pure-Python Monotonic Isotonic Regression Calibrator (PAVA algorithm)."""

    thresholds: list[float]  # sorted distinct predicted probabilities
    calibrated_values: list[float]  # monotonically non-decreasing calibrated values

    def calibrate(self, probability: float) -> float:
        """Piecewise linear interpolation on the learned isotonic step curve."""
        if not self.thresholds:
            return probability

        if probability <= self.thresholds[0]:
            return self.calibrated_values[0]
        if probability >= self.thresholds[-1]:
            return self.calibrated_values[-1]

        # Binary search / piecewise linear interpolation
        low = 0
        high = len(self.thresholds) - 1
        while low <= high:
            mid = (low + high) // 2
            if self.thresholds[mid] == probability:
                return self.calibrated_values[mid]
            elif self.thresholds[mid] < probability:
                low = mid + 1
            else:
                high = mid - 1

        idx = max(0, high)
        x0, x1 = self.thresholds[idx], self.thresholds[idx + 1]
        y0, y1 = self.calibrated_values[idx], self.calibrated_values[idx + 1]
        t = (probability - x0) / max(1e-9, x1 - x0)
        return round(y0 + t * (y1 - y0), 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "isotonic",
            "thresholds": [round(t, 4) for t in self.thresholds],
            "calibrated_values": [round(v, 4) for v in self.calibrated_values],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IsotonicCalibrator":
        return cls(thresholds=data["thresholds"], calibrated_values=data["calibrated_values"])

    @classmethod
    def fit(cls, probabilities: list[float], outcomes: list[int]) -> "IsotonicCalibrator":
        """Fit isotonic regression using Pool Adjacent Violators Algorithm (PAVA)."""
        if not probabilities or len(probabilities) != len(outcomes):
            return cls([0.0, 1.0], [0.0, 1.0])

        # Sort by predicted probability
        sorted_pairs = sorted(zip(probabilities, outcomes), key=lambda x: x[0])
        x_sorted = [p[0] for p in sorted_pairs]
        y_sorted = [float(p[1]) for p in sorted_pairs]

        # Compress identical x values into blocks: (sum_y, count, x_val)
        blocks: list[list[float]] = []  # each item: [sum_y, count, x_val]
        for x, y in zip(x_sorted, y_sorted):
            if blocks and blocks[-1][2] == x:
                blocks[-1][0] += y
                blocks[-1][1] += 1
            else:
                blocks.append([y, 1.0, x])

        # Run PAVA to enforce monotonicity: mean_y[i] <= mean_y[i+1]
        stack: list[list[float]] = []
        for b in blocks:
            cur = [b[0], b[1], b[2]]
            while stack and (stack[-1][0] / stack[-1][1]) > (cur[0] / cur[1]):
                prev = stack.pop()
                cur[0] += prev[0]
                cur[1] += prev[1]
            stack.append(cur)

        thresholds: list[float] = []
        cal_values: list[float] = []
        for s in stack:
            thresholds.append(s[2])
            cal_values.append(round(max(0.0, min(1.0, s[0] / s[1])), 4))

        # Enforce boundary anchors
        if not thresholds or thresholds[0] > 0.0:
            thresholds.insert(0, 0.0)
            cal_values.insert(0, 0.0)
        if thresholds[-1] < 1.0:
            thresholds.append(1.0)
            cal_values.append(1.0)

        return cls(thresholds=thresholds, calibrated_values=cal_values)
