"""Phase 2 deep diagnostics — pure detectors over diagnostic signals.

Inputs are dicts of {series_name: list[(x_value, y_value)]}.
Detectors must:
- check that the required signal is present;
- return None when the signal is missing or evidence is insufficient;
- return a Finding when the heuristic threshold fires;
- never claim root cause.

This module must not import from store, api, or any I/O layer.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from analytics_engine.diagnostics_schemas import EpochRange, Finding

# =========================
# Heuristic thresholds (v2)
# =========================
# Tuning constants encode the heuristic v2 contract; they are NOT claims about
# "true" learning dynamics.

V2_GRAD_VANISH_GEOMEAN = 1e-5  # heuristic v2
V2_GRAD_EXPLODE_ABS = 1000.0  # heuristic v2
V2_GRAD_EXPLODE_SPIKE_MULT = 100.0  # heuristic v2
V2_GRAD_DECAY_SLOPE = -0.5  # heuristic v2
V2_LR_HIGH_OSC_SIGN_CHANGES = 3  # heuristic v2
V2_LR_LOW_LOG_LOSS_SLOPE = -0.001  # heuristic v2
V2_WEIGHT_EXPLOSION_MULT = 5.0  # heuristic v2

ASSUMPTION_HEURISTIC_V2 = (
    "Heuristic diagnostics v2 — gradient/loss/lr/weight signals interpreted "
    "with conservative thresholds; results are signals, not causes."
)

DiagnosticSignals = dict[str, list[tuple[float, float]]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _series(signals: DiagnosticSignals | None, name: str) -> list[tuple[float, float]] | None:
    if signals is None:
        return None
    pts = signals.get(name)
    if pts is None or not pts:
        return None
    return [(float(x), float(y)) for x, y in pts]


def _x_range(points: list[tuple[float, float]]) -> EpochRange | None:
    if not points:
        return None
    return EpochRange(start=float(points[0][0]), end=float(points[-1][0]))


def _last_half(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    n = len(points)
    if n <= 1:
        return list(points)
    k = max(1, n // 2)
    return points[-k:]


def _geomean_positive(values: Iterable[float]) -> float | None:
    """Geometric mean of strictly positive values; None if empty or any non-positive."""

    arr = [float(v) for v in values]
    if not arr:
        return None
    total = 0.0
    for v in arr:
        if v <= 0.0 or not math.isfinite(v):
            return None
        total += math.log(v)
    return math.exp(total / len(arr))


def _median(values: Iterable[float]) -> float | None:
    arr = sorted(float(v) for v in values)
    n = len(arr)
    if n == 0:
        return None
    if n % 2 == 1:
        return arr[n // 2]
    return 0.5 * (arr[n // 2 - 1] + arr[n // 2])


def _least_squares_slope(xs: list[float], ys: list[float]) -> float | None:
    """Return slope of the OLS regression of ys on xs, or None if undefined."""

    n = len(xs)
    if n != len(ys) or n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = 0.0
    den = 0.0
    for x, y in zip(xs, ys, strict=False):
        dx = x - mean_x
        num += dx * (y - mean_y)
        den += dx * dx
    if den == 0.0:
        return None
    return num / den


def _sign_changes_in_deltas(values: list[float]) -> int:
    """Count sign changes in consecutive deltas of values."""

    if len(values) < 3:
        return 0
    deltas = [b - a for a, b in zip(values, values[1:], strict=False)]
    changes = 0
    prev_sign = 0
    for d in deltas:
        if d > 0:
            sign = 1
        elif d < 0:
            sign = -1
        else:
            continue
        if prev_sign != 0 and sign != prev_sign:
            changes += 1
        prev_sign = sign
    return changes


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def detect_vanishing_gradient(signals: DiagnosticSignals | None) -> Finding | None:
    pts = _series(signals, "grad_norm_global") or _series(signals, "grad_norm_first_layer")
    if pts is None or len(pts) < 2:
        return None
    tail = _last_half(pts)
    geomean = _geomean_positive(y for _, y in tail)
    if geomean is None or geomean >= V2_GRAD_VANISH_GEOMEAN:
        return None
    return Finding(
        kind="vanishing_gradient",
        severity="critical",
        title="Gradient magnitude is very small in late phase",
        description=(
            "This signal may indicate vanishing gradients: the geometric mean "
            "of gradient norm over the last half of training is below the "
            "vanishing-gradient threshold."
        ),
        epoch_range=_x_range(tail),
        evidence={
            "geomean_last_half": float(geomean),
            "threshold": V2_GRAD_VANISH_GEOMEAN,
            "n_points": len(tail),
        },
        suggested_checks=[
            "Check whether initialization scale changes late gradient magnitude.",
            "Check whether normalization layers change gradient magnitude.",
            "Check whether activation choice affects gradient saturation.",
            "Check whether residual connections change gradient flow.",
        ],
    )


def detect_exploding_gradient(signals: DiagnosticSignals | None) -> Finding | None:
    pts = _series(signals, "grad_norm_global")
    if pts is None or len(pts) < 2:
        return None
    ys = [y for _, y in pts]
    max_val = max(ys)
    med = _median(ys)
    spike_threshold: float | None = None
    if med is not None and med > 0:
        spike_threshold = V2_GRAD_EXPLODE_SPIKE_MULT * med
    abs_trigger = max_val > V2_GRAD_EXPLODE_ABS
    spike_trigger = spike_threshold is not None and any(y > spike_threshold for y in ys)
    if not (abs_trigger or spike_trigger):
        return None
    evidence: dict[str, float | int | str] = {
        "max_grad_norm": float(max_val),
        "abs_threshold": V2_GRAD_EXPLODE_ABS,
    }
    if med is not None:
        evidence["median_grad_norm"] = float(med)
    if spike_threshold is not None:
        evidence["spike_threshold"] = float(spike_threshold)
    return Finding(
        kind="exploding_gradient",
        severity="critical",
        title="Gradient norm shows large magnitude or spike",
        description=(
            "This signal may indicate exploding gradients: gradient norm "
            "exceeds the absolute threshold or spikes well above the median."
        ),
        epoch_range=_x_range(pts),
        evidence=evidence,
        suggested_checks=[
            "Check whether gradient clipping reduces gradient spikes.",
            "Check whether lower learning rate reduces gradient spikes.",
            "Check whether loss values remain finite around gradient spikes.",
            "Check whether initialization scale changes early gradient magnitude.",
        ],
    )


def detect_gradient_norm_decay(signals: DiagnosticSignals | None) -> Finding | None:
    pts = _series(signals, "grad_norm_global")
    if pts is None or len(pts) < 3:
        return None
    xs = [x for x, _ in pts]
    log_ys: list[float] = []
    log_xs: list[float] = []
    for x, y in pts:
        if y <= 0.0 or not math.isfinite(y):
            continue
        log_ys.append(math.log(y))
        log_xs.append(float(x))
    if len(log_ys) < 3:
        return None
    slope = _least_squares_slope(log_xs, log_ys)
    if slope is None or slope >= V2_GRAD_DECAY_SLOPE:
        return None
    return Finding(
        kind="gradient_norm_decay",
        severity="warn",
        title="Gradient magnitude decays quickly",
        description=(
            "Gradient magnitude decreases quickly. This is consistent with "
            "convergence or saturation and should be interpreted together "
            "with validation behavior."
        ),
        epoch_range=_x_range(pts),
        evidence={
            "log_slope": float(slope),
            "threshold": V2_GRAD_DECAY_SLOPE,
            "n_points": len(log_ys),
            "x_first": float(xs[0]),
            "x_last": float(xs[-1]),
        },
        suggested_checks=[
            "Check whether validation improves while gradient magnitude decays.",
            "Check whether train loss keeps improving while gradients decay.",
            "Check whether longer training changes the late validation curve.",
        ],
    )


def detect_learning_rate_too_high(signals: DiagnosticSignals | None) -> Finding | None:
    lr = _series(signals, "lr")
    if lr is None or len(lr) < 2:
        return None
    if not all(y > 0 for _, y in lr):
        return None
    loss = _series(signals, "loss_train") or _series(signals, "loss_val")
    if loss is None or len(loss) < 4:
        return None
    tail = _last_half(loss)
    if len(tail) < 3:
        return None
    sign_changes = _sign_changes_in_deltas([y for _, y in tail])
    if sign_changes < V2_LR_HIGH_OSC_SIGN_CHANGES:
        return None
    return Finding(
        kind="learning_rate_too_high",
        severity="warn",
        title="Loss oscillates with positive learning rate",
        description=(
            "This signal may indicate that the learning rate is too high: the "
            "loss curve shows multiple sign changes in its late deltas while "
            "the learning rate stays positive."
        ),
        epoch_range=_x_range(tail),
        evidence={
            "sign_changes_last_half": int(sign_changes),
            "threshold": V2_LR_HIGH_OSC_SIGN_CHANGES,
            "n_points_last_half": len(tail),
        },
        suggested_checks=[
            "Check whether lower learning rate reduces loss oscillation.",
            "Check whether warmup changes early loss oscillation.",
            "Check whether a smoother schedule changes late validation stability.",
        ],
    )


def detect_learning_rate_too_low(signals: DiagnosticSignals | None) -> Finding | None:
    lr = _series(signals, "lr")
    loss = _series(signals, "loss_train")
    if lr is None or loss is None or len(loss) < 4:
        return None
    deltas = [b - a for a, b in zip([y for _, y in loss], [y for _, y in loss][1:], strict=False)]
    if not deltas:
        return None
    n_non_increasing = sum(1 for d in deltas if d <= 0.0)
    if n_non_increasing / len(deltas) < 0.8:
        return None
    tail = _last_half(loss)
    log_xs: list[float] = []
    log_ys: list[float] = []
    for x, y in tail:
        if y <= 0.0 or not math.isfinite(y):
            continue
        log_xs.append(float(x))
        log_ys.append(math.log(y))
    if len(log_ys) < 3:
        return None
    slope = _least_squares_slope(log_xs, log_ys)
    if slope is None or slope <= V2_LR_LOW_LOG_LOSS_SLOPE:
        return None
    return Finding(
        kind="learning_rate_too_low",
        severity="info",
        title="Train loss decreases slowly",
        description=(
            "This signal may indicate that the learning rate is too low: train "
            "loss is near-monotonically non-increasing but the late log-loss "
            "slope is shallow."
        ),
        epoch_range=_x_range(tail),
        evidence={
            "log_loss_slope_last_half": float(slope),
            "threshold": V2_LR_LOW_LOG_LOSS_SLOPE,
            "fraction_non_increasing": float(n_non_increasing / len(deltas)),
        },
        suggested_checks=[
            "Check whether a learning-rate range test changes loss descent speed.",
            "Check whether a higher base learning rate with warmup changes train loss slope.",
            "Check whether additional budget changes the late loss slope.",
        ],
    )


def detect_weight_norm_explosion(signals: DiagnosticSignals | None) -> Finding | None:
    pts = _series(signals, "weight_norm_global")
    if pts is None or len(pts) < 2:
        return None
    initial = float(pts[0][1])
    final = float(pts[-1][1])
    if initial <= 0.0 or not math.isfinite(initial) or not math.isfinite(final):
        return None
    if final <= V2_WEIGHT_EXPLOSION_MULT * initial:
        return None
    return Finding(
        kind="weight_norm_explosion",
        severity="warn",
        title="Weight norm grew sharply during training",
        description=(
            "This signal may indicate weight norm explosion: the final weight "
            "norm exceeds several times the initial weight norm."
        ),
        epoch_range=_x_range(pts),
        evidence={
            "initial_weight_norm": float(initial),
            "final_weight_norm": float(final),
            "ratio": float(final / initial),
            "threshold_mult": V2_WEIGHT_EXPLOSION_MULT,
        },
        suggested_checks=[
            "Check whether weight decay changes weight norm growth.",
            "Check whether gradient clipping changes weight norm growth.",
            "Check whether loss values remain bounded during weight norm growth.",
        ],
    )


_V2_DETECTORS = (
    detect_vanishing_gradient,
    detect_exploding_gradient,
    detect_gradient_norm_decay,
    detect_learning_rate_too_high,
    detect_learning_rate_too_low,
    detect_weight_norm_explosion,
)


def run_v2_detectors(signals: DiagnosticSignals | None) -> list[Finding]:
    """Run all v2 detectors against the provided diagnostic signals."""

    if signals is None:
        return []
    out: list[Finding] = []
    for det in _V2_DETECTORS:
        f = det(signals)
        if f is not None:
            out.append(f)
    return out
