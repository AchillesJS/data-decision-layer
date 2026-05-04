from __future__ import annotations

import statistics
from collections.abc import Callable

from analytics_engine.diagnostics_schemas import (
    DiagnosisReport,
    DiagnosticsInput,
    EpochRange,
    Finding,
    Severity,
)

# =========================
# Heuristic thresholds (v1)
# =========================
# These constants encode the heuristic v1 contract and are NOT claims about
# "true" learning dynamics. They tune conservative, signal-only detectors.

D_MIN_VAL_POINTS = 5
D_COLD_START_WINDOW_FRAC = 0.3
D_COLD_START_DELTA = 0.01
D_PLATEAU_WINDOW_FRAC = 0.5
D_PLATEAU_DELTA = 0.005
D_OVERFIT_GAP_GROWTH = 0.03
D_OVERFIT_LAST_FRAC = 0.3
D_LATE_COLLAPSE_DROP = 0.02
D_HIGH_VAR_STD = 0.03
D_HIGH_VAR_WINDOW_FRAC = 0.3
D_TRAIN_UNDERFIT_MAX = 0.6
D_PREMATURE_SAT_FRAC = 0.3

# Severity escalation thresholds (local; not part of the spec table).
_OVERFIT_CRITICAL_GAP = 0.06
_LATE_COLLAPSE_CRITICAL_DROP = 0.05
_PLATEAU_HIGH_FINAL = 0.7

_LOSS_KEYWORDS = ("loss", "error", "mae", "mse")

ASSUMPTION_HEURISTIC_V1 = (
    "Heuristic diagnostics v1 — signals derived from normalized "
    "train/val metric curves only."
)

_SEVERITY_ORDER: dict[str, int] = {"critical": 0, "warn": 1, "info": 2}


def _is_strictly_increasing(xs: list[float]) -> bool:
    return all(b > a for a, b in zip(xs, xs[1:], strict=False))


def _x_range_from_points(points: list[tuple[float, float]]) -> EpochRange | None:
    if not points:
        return None
    return EpochRange(start=float(points[0][0]), end=float(points[-1][0]))


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def detect_insufficient_data(inp: DiagnosticsInput) -> Finding | None:
    n = len(inp.val_series)
    if n >= D_MIN_VAL_POINTS:
        return None
    return Finding(
        kind="insufficient_data",
        severity="info",
        title="Insufficient validation points for diagnostics",
        description=(
            "This signal may indicate that fewer than "
            f"{D_MIN_VAL_POINTS} validation points are available; v1 diagnostics "
            f"need at least {D_MIN_VAL_POINTS} val points."
        ),
        epoch_range=_x_range_from_points(inp.val_series),
        evidence={"n_val_points": n, "min_required": D_MIN_VAL_POINTS},
        suggested_checks=[
            "Check whether the run can emit at least 5 validation points.",
        ],
    )


def detect_invalid_series(inp: DiagnosticsInput) -> Finding | None:
    val_xs = [x for x, _ in inp.val_series]
    train_xs = [x for x, _ in inp.train_series]
    val_bad = len(val_xs) >= 2 and not _is_strictly_increasing(val_xs)
    train_bad = len(train_xs) >= 2 and not _is_strictly_increasing(train_xs)
    if not (val_bad or train_bad):
        return None
    if val_bad and train_bad:
        where = "val and train"
    elif val_bad:
        where = "val"
    else:
        where = "train"
    return Finding(
        kind="invalid_series",
        severity="warn",
        title="Non-monotonic x values in metric series",
        description=(
            f"This signal may indicate that {where} x_values are not strictly "
            "increasing; curve diagnostics require monotonic x."
        ),
        evidence={"series": where},
        suggested_checks=[
            "Check whether metric logging writes monotonically increasing epoch or step values.",
        ],
    )


def detect_unsupported_metric_scale(inp: DiagnosticsInput) -> Finding | None:
    name = inp.metric_name.lower()
    if not any(k in name for k in _LOSS_KEYWORDS):
        return None
    return Finding(
        kind="unsupported_metric_scale",
        severity="info",
        title="Metric is not a normalized quality score",
        description=(
            "This signal may indicate that the metric is loss/error/MAE/MSE; "
            "v1 diagnostics only support normalized quality scores in [0, 1] "
            "where higher is better."
        ),
        evidence={"metric_name": inp.metric_name},
        suggested_checks=[
            "Check whether this metric can be converted into a normalized quality score before curve diagnostics.",
        ],
    )


def detect_cold_start_failure(inp: DiagnosticsInput) -> Finding | None:
    val = inp.val_series
    n = len(val)
    if n == 0:
        return None
    k = max(2, int(n * D_COLD_START_WINDOW_FRAC))
    k = min(k, n)
    window = val[:k]
    y0 = window[0][1]
    y_max = max(y for _, y in window)
    delta = y_max - y0
    if delta >= D_COLD_START_DELTA:
        return None
    return Finding(
        kind="cold_start_failure",
        severity="critical",
        title="Cold-start failure: validation barely moves",
        description=(
            "This signal may indicate that the model did not start learning in "
            "the early phase; validation gain is below the cold-start threshold."
        ),
        epoch_range=_x_range_from_points(window),
        evidence={
            "window_size": k,
            "delta_within_window": float(delta),
            "threshold": D_COLD_START_DELTA,
        },
        suggested_checks=[
            "Check whether the learning rate is non-zero and finite.",
            "Check whether the model is in train mode.",
            "Check whether the dataloader yields non-degenerate batches.",
            "Check whether the loss is finite at the first step.",
        ],
    )


def detect_plateau_late(inp: DiagnosticsInput) -> Finding | None:
    val = inp.val_series
    n = len(val)
    if n == 0:
        return None
    k = max(3, int(n * D_PLATEAU_WINDOW_FRAC))
    k = min(k, n)
    window = val[-k:]
    ys = [y for _, y in window]
    span = max(ys) - min(ys)
    if span >= D_PLATEAU_DELTA:
        return None
    final_val = val[-1][1]
    severity: Severity = "info" if final_val >= _PLATEAU_HIGH_FINAL else "warn"
    return Finding(
        kind="plateau_late",
        severity=severity,
        title="Validation plateau in late phase",
        description=(
            "This signal may indicate that validation has plateaued near the "
            "end of training; recent variation is below the plateau threshold."
        ),
        epoch_range=_x_range_from_points(window),
        evidence={
            "window_size": k,
            "span_within_window": float(span),
            "final_val": float(final_val),
        },
        suggested_checks=[
            "Check whether cohort-level saturation analysis confirms low marginal gain.",
            "Check whether a learning rate decay changes the late plateau.",
            "Check whether early stopping at the plateau produces the same validation score.",
        ],
    )


def _align_train_val_by_x(
    val: list[tuple[float, float]],
    train: list[tuple[float, float]],
) -> list[tuple[float, float, float]]:
    """Inner-join train and val by exact x; returns (x, train_y, val_y)."""
    train_by_x: dict[float, float] = {x: y for x, y in train}
    out: list[tuple[float, float, float]] = []
    for x, vy in val:
        if x in train_by_x:
            out.append((float(x), float(train_by_x[x]), float(vy)))
    return out


def detect_overfitting_divergence(inp: DiagnosticsInput) -> Finding | None:
    if not inp.train_series:
        return None
    aligned = _align_train_val_by_x(inp.val_series, inp.train_series)
    n = len(aligned)
    if n < 4:
        return None
    k = max(2, int(n * D_OVERFIT_LAST_FRAC))
    k = min(k, n - 1)
    early = aligned[:-k]
    late = aligned[-k:]
    if not early or not late:
        return None

    early_gap = sum(t - v for _, t, v in early) / len(early)
    late_gap = sum(t - v for _, t, v in late) / len(late)
    gap_growth = late_gap - early_gap

    early_train = sum(t for _, t, _ in early) / len(early)
    late_train = sum(t for _, t, _ in late) / len(late)
    early_val = sum(v for _, _, v in early) / len(early)
    late_val = sum(v for _, _, v in late) / len(late)
    train_improve = late_train - early_train
    val_improve = late_val - early_val

    if gap_growth <= D_OVERFIT_GAP_GROWTH:
        return None
    if train_improve <= val_improve:
        return None

    severity: Severity = "critical" if gap_growth >= _OVERFIT_CRITICAL_GAP else "warn"
    late_xs = [(x, y) for x, _, y in late]  # use val pairs for epoch range
    return Finding(
        kind="overfitting_divergence",
        severity=severity,
        title="Train/val divergence consistent with overfitting",
        description=(
            "This signal may indicate train/val divergence: the train-minus-val "
            "gap grew while train improved more than val in the late window."
        ),
        epoch_range=_x_range_from_points(late_xs),
        evidence={
            "gap_growth": float(gap_growth),
            "early_gap": float(early_gap),
            "late_gap": float(late_gap),
            "train_improve": float(train_improve),
            "val_improve": float(val_improve),
        },
        suggested_checks=[
            "Check whether stronger regularization reduces the train/val gap.",
            "Check whether data augmentation changes validation stability.",
            "Check whether early stopping near the validation peak changes the final result.",
            "Check whether additional data changes the train/val gap.",
        ],
    )


def detect_late_collapse(inp: DiagnosticsInput) -> Finding | None:
    val = inp.val_series
    if len(val) < 3:
        return None
    ys = [y for _, y in val]
    peak_idx = max(range(len(ys)), key=lambda i: ys[i])
    if peak_idx == len(ys) - 1:
        return None
    drop = ys[peak_idx] - ys[-1]
    if drop <= D_LATE_COLLAPSE_DROP:
        return None
    severity: Severity = "critical" if drop >= _LATE_COLLAPSE_CRITICAL_DROP else "warn"
    return Finding(
        kind="late_collapse",
        severity=severity,
        title="Late collapse: validation drops after peak",
        description=(
            "This signal may indicate that validation peaked before the final "
            "point and dropped by more than the late-collapse threshold."
        ),
        epoch_range=EpochRange(start=float(val[peak_idx][0]), end=float(val[-1][0])),
        evidence={
            "peak_x": float(val[peak_idx][0]),
            "peak_val": float(ys[peak_idx]),
            "final_val": float(ys[-1]),
            "drop": float(drop),
        },
        suggested_checks=[
            "Check whether early stopping at the validation peak preserves performance.",
            "Check whether the learning rate schedule is linked to the late drop.",
            "Check whether validation distribution differs from training distribution.",
        ],
    )


def detect_high_variance(inp: DiagnosticsInput) -> Finding | None:
    val = inp.val_series
    n = len(val)
    if n < 4:
        return None
    k = max(3, int(n * D_HIGH_VAR_WINDOW_FRAC))
    k = min(k, n)
    window = val[-k:]
    ys = [y for _, y in window]
    deltas = [b - a for a, b in zip(ys, ys[1:], strict=False)]
    if len(deltas) < 2:
        return None
    std = statistics.pstdev(deltas)
    if std <= D_HIGH_VAR_STD:
        return None
    return Finding(
        kind="high_variance",
        severity="warn",
        title="High validation variance in late phase",
        description=(
            "This signal may indicate that validation oscillates strongly in "
            "the late window; std of consecutive deltas exceeds the threshold."
        ),
        epoch_range=_x_range_from_points(window),
        evidence={
            "window_size": k,
            "std_of_deltas": float(std),
            "threshold": D_HIGH_VAR_STD,
        },
        suggested_checks=[
            "Check whether a lower learning rate reduces validation oscillation.",
            "Check whether gradient clipping reduces metric spikes.",
            "Check whether a larger batch or accumulation reduces validation variance.",
            "Check whether EMA evaluation reduces validation oscillation.",
        ],
    )


def detect_train_underfitting(inp: DiagnosticsInput) -> Finding | None:
    train = inp.train_series
    n = len(train)
    if n < 4:
        return None
    k = max(3, int(n * D_PLATEAU_WINDOW_FRAC))
    k = min(k, n)
    window = train[-k:]
    ys = [y for _, y in window]
    span = max(ys) - min(ys)
    if span >= D_PLATEAU_DELTA:
        return None
    train_final = train[-1][1]
    if train_final >= D_TRAIN_UNDERFIT_MAX:
        return None
    return Finding(
        kind="train_underfitting",
        severity="warn",
        title="Train curve plateaued at low performance",
        description=(
            "This signal may indicate train underfitting: the train curve "
            "plateaus and final train performance is below the underfit threshold."
        ),
        epoch_range=_x_range_from_points(window),
        evidence={
            "window_size": k,
            "train_final": float(train_final),
            "span_within_window": float(span),
            "threshold": D_TRAIN_UNDERFIT_MAX,
        },
        suggested_checks=[
            "Check whether the model can overfit a single small batch.",
            "Check whether a larger model changes train performance.",
            "Check whether additional epochs improve the train curve.",
            "Check whether input and label alignment is correct.",
        ],
    )


def detect_premature_saturation(inp: DiagnosticsInput) -> Finding | None:
    val = inp.val_series
    n = len(val)
    if n < D_MIN_VAL_POINTS:
        return None
    k = max(3, int(n * D_PLATEAU_WINDOW_FRAC))
    if k >= n:
        return None
    sat_start: int | None = None
    for start in range(0, n - k + 1):
        window = [y for _, y in val[start : start + k]]
        if max(window) - min(window) < D_PLATEAU_DELTA:
            sat_start = start
            break
    if sat_start is None:
        return None
    fraction = sat_start / n
    if fraction >= D_PREMATURE_SAT_FRAC:
        return None
    return Finding(
        kind="premature_saturation",
        severity="info",
        title="Saturation detected in early phase",
        description=(
            "This signal may indicate that validation saturated within the "
            "early portion of the run; the first plateau window starts before "
            f"{int(D_PREMATURE_SAT_FRAC * 100)}% of the run."
        ),
        epoch_range=EpochRange(
            start=float(val[sat_start][0]),
            end=float(val[sat_start + k - 1][0]),
        ),
        evidence={
            "saturation_start_index": int(sat_start),
            "n_val_points": int(n),
            "fraction": float(fraction),
        },
        suggested_checks=[
            "Check whether a shorter budget reaches the same validation score.",
            "Check whether other findings explain why saturation happens early.",
        ],
    )


# Stable order for findings inside the same severity bucket.
_DETECTORS: list[Callable[[DiagnosticsInput], Finding | None]] = [
    detect_cold_start_failure,
    detect_plateau_late,
    detect_overfitting_divergence,
    detect_late_collapse,
    detect_high_variance,
    detect_train_underfitting,
    detect_premature_saturation,
]


def diagnose(inp: DiagnosticsInput) -> DiagnosisReport:
    """Run all v1 detectors and return a sorted DiagnosisReport.

    Short-circuits, in order:
      1) unsupported_metric_scale
      2) invalid_series
      3) insufficient_data
    Otherwise runs all detectors and sorts findings by severity
    (critical > warn > info), preserving stable order inside the same severity.
    """
    n_val = len(inp.val_series)
    n_train = len(inp.train_series)
    assumptions = [ASSUMPTION_HEURISTIC_V1]

    def _wrap(findings: list[Finding]) -> DiagnosisReport:
        return DiagnosisReport(
            run_id=inp.run_id,
            metric_name=inp.metric_name,
            n_val_points=n_val,
            n_train_points=n_train,
            findings=findings,
            assumptions=assumptions,
        )

    unsupported = detect_unsupported_metric_scale(inp)
    if unsupported is not None:
        return _wrap([unsupported])

    invalid = detect_invalid_series(inp)
    if invalid is not None:
        return _wrap([invalid])

    insufficient = detect_insufficient_data(inp)
    if insufficient is not None:
        return _wrap([insufficient])

    findings: list[Finding] = []
    for det in _DETECTORS:
        f = det(inp)
        if f is not None:
            findings.append(f)

    findings.sort(key=lambda f: _SEVERITY_ORDER[f.severity])
    return _wrap(findings)
