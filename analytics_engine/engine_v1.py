from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias, cast

import numpy as np
import numpy.typing as npt
from pydantic import ValidationError

from analytics_engine.schemas import (
    DataPotentialDraft,
    FitCoverage,
    FitReport,
    FitSanity,
    RegimeEstimate,
    RegimeSignal,
    RunPoint,
    SaturationEstimate,
)

ModelFamily: TypeAlias = Literal["log", "power", "none"]
FitQuality: TypeAlias = Literal["ok", "weak", "bad", "insufficient_data"]
Regime: TypeAlias = Literal[
    "DATA_LIMITED",
    "MODEL_LIMITED",
    "NOISE_LIMITED",
    "OPTIMIZATION_LIMITED",
    "UNKNOWN",
]
ModelParams: TypeAlias = tuple[float, float] | tuple[float, float, float]
FloatArray: TypeAlias = npt.NDArray[np.float64]


@dataclass(frozen=True)
class _GroupedX:
    x: float
    y_mean: float
    y_std: float
    count: int
    run_ids: tuple[str, ...]


def _safe_float(v: float) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    raise TypeError("not numeric")


def _coerce_run_points(items: Sequence[RunPoint | dict]) -> list[RunPoint]:
    out: list[RunPoint] = []
    for it in items:
        if isinstance(it, RunPoint):
            rp = it
        else:
            try:
                rp = RunPoint.model_validate(it)
            except ValidationError:
                continue

        # Preprocess contract: drop invalid y (not 0..1) or x<=0
        try:
            x = _safe_float(rp.x_value)
            y = _safe_float(rp.y_value)
        except TypeError:
            continue

        if x <= 0:
            continue
        if y < 0 or y > 1:
            continue
        out.append(rp)
    return out


def _group_by_x(run_points: Sequence[RunPoint]) -> list[_GroupedX]:
    buckets: dict[float, list[RunPoint]] = {}
    for rp in run_points:
        buckets.setdefault(float(rp.x_value), []).append(rp)

    grouped: list[_GroupedX] = []
    for x, pts in buckets.items():
        ys = np.asarray([p.y_value for p in pts], dtype=np.float64)
        y_mean = float(ys.mean())
        y_std = float(ys.std(ddof=0)) if len(ys) >= 2 else 0.0
        grouped.append(
            _GroupedX(
                x=float(x),
                y_mean=y_mean,
                y_std=y_std,
                count=len(pts),
                run_ids=tuple(p.run_id for p in pts),
            )
        )
    grouped.sort(key=lambda g: g.x)
    return grouped


def _monotonic_violations(grouped: Sequence[_GroupedX], tol: float = 0.01) -> list[str]:
    violations: list[str] = []
    for prev, cur in zip(grouped, grouped[1:], strict=False):
        if cur.y_mean < prev.y_mean - tol:
            violations.append(
                f"y decreased from {prev.y_mean:.4f} to {cur.y_mean:.4f} at x {prev.x:g}->{cur.x:g}"
            )
    return violations


def _r2(y_true: FloatArray, y_pred: FloatArray) -> float | None:
    if y_true.size < 2:
        return None
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - float(y_true.mean())) ** 2))
    if ss_tot <= 1e-12:
        return None
    return 1.0 - ss_res / ss_tot


def _mae(y_true: FloatArray, y_pred: FloatArray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _log_fit(x: FloatArray, y: FloatArray) -> tuple[float, float] | None:
    # y = a + b*log(x)
    if np.any(x <= 0):
        return None
    X = np.column_stack([np.ones_like(x), np.log(x)])
    try:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    a, b = float(coef[0]), float(coef[1])
    return a, b


def _log_predict(params: tuple[float, float], x: FloatArray) -> FloatArray:
    a, b = params
    return np.asarray(a + b * np.log(x), dtype=np.float64)


def _power_fit_grid(x: FloatArray, y: FloatArray) -> tuple[float, float, float] | None:
    # y = c - d*(x**(-k)), k>0
    if np.any(x <= 0):
        return None

    best: tuple[float, float, float, float] | None = None  # (mae, c, d, k)
    ks = np.linspace(0.1, 3.0, 60)
    for k in ks:
        z = x ** (-k)
        X = np.column_stack([np.ones_like(z), z])  # y = c + m*z, where m = -d
        try:
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        c = float(coef[0])
        m = float(coef[1])
        d = -m

        if d < 0:
            continue
        if not (0.0 <= c <= 1.0):
            continue

        y_pred = np.asarray(c - d * (x ** (-k)), dtype=np.float64)
        if np.any(y_pred < -1e-6) or np.any(y_pred > 1 + 1e-6):
            continue
        err = _mae(y, y_pred)
        if best is None or err < best[0]:
            best = (err, c, d, float(k))

    if best is None:
        return None
    _, c, d, k = best
    return c, d, k


def _power_predict(params: tuple[float, float, float], x: FloatArray) -> FloatArray:
    c, d, k = params
    return np.asarray(c - d * (x ** (-k)), dtype=np.float64)


def _fit_quality(mae: float | None, r2: float | None) -> FitQuality:
    if mae is None:
        return "bad"
    if mae <= 0.02 and (r2 is not None and r2 >= 0.5):
        return "ok"
    if mae <= 0.05:
        return "weak"
    return "bad"


def _choose_model(
    grouped: Sequence[_GroupedX],
) -> tuple[ModelFamily, ModelParams | None, FloatArray | None, float | None, float | None, list[str]]:
    x: FloatArray = np.asarray([g.x for g in grouped], dtype=np.float64)
    y: FloatArray = np.asarray([g.y_mean for g in grouped], dtype=np.float64)
    violations: list[str] = []

    best_family: ModelFamily = "none"
    best_params: ModelParams | None = None
    best_pred: FloatArray | None = None
    best_mae: float | None = None
    best_r2: float | None = None

    # Log candidate
    log_params = _log_fit(x, y)
    if log_params is not None:
        pred = _log_predict(log_params, x)
        if np.any(pred < -1e-6) or np.any(pred > 1 + 1e-6):
            violations.append("log_pred_out_of_bounds")
        else:
            mae = _mae(y, pred)
            r2v = _r2(y, pred)
            best_family, best_params, best_pred, best_mae, best_r2 = (
                "log",
                log_params,
                pred,
                mae,
                r2v,
            )

    # Power candidate
    power_params = _power_fit_grid(x, y)
    if power_params is not None:
        pred = _power_predict(power_params, x)
        mae = _mae(y, pred)
        r2v = _r2(y, pred)
        if best_mae is None or mae < best_mae:
            best_family, best_params, best_pred, best_mae, best_r2 = (
                "power",
                power_params,
                pred,
                mae,
                r2v,
            )

    return best_family, best_params, best_pred, best_mae, best_r2, violations


def _estimate_from_model(
    family: ModelFamily,
    params: ModelParams | None,
    x_max: float,
    current: float,
    pcts: tuple[float, float],
) -> tuple[float, float, float]:
    """Return (ceiling, gain_p20, gain_p50)."""

    def predict_at(xx: float) -> float:
        x_arr: FloatArray = np.asarray([xx], dtype=np.float64)
        if family == "power" and params is not None:
            p = cast(tuple[float, float, float], params)
            y = float(_power_predict(p, x_arr)[0])
        elif family == "log" and params is not None:
            p = cast(tuple[float, float], params)
            y = float(_log_predict(p, x_arr)[0])
        else:
            y = float("nan")
        return float(np.clip(y, 0.0, 1.0))

    if family == "power" and params is not None:
        p = cast(tuple[float, float, float], params)
        ceiling = float(np.clip(float(p[0]), 0.0, 1.0))  # c
    elif family == "log" and params is not None:
        # Honest heuristic: log has no ceiling; project at 10x max-x, clamp to [0,1]
        ceiling = predict_at(x_max * 10.0)
    else:
        # No fit: conservative small headroom; low confidence handled elsewhere
        ceiling = float(min(1.0, max(current, current + 0.10)))

    gain_20 = predict_at(x_max * (1.0 + pcts[0])) - current
    gain_50 = predict_at(x_max * (1.0 + pcts[1])) - current
    return ceiling, gain_20, gain_50


def _bootstrap_ranges(
    grouped: Sequence[_GroupedX],
    family: ModelFamily,
    pcts: tuple[float, float],
    n_boot: int,
    rng: np.random.Generator,
    current: float,
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    if len(grouped) == 0:
        return (current, current), (0.0, 0.0), (0.0, 0.0)

    x_all: FloatArray = np.asarray([g.x for g in grouped], dtype=np.float64)
    y_all: FloatArray = np.asarray([g.y_mean for g in grouped], dtype=np.float64)
    x_max = float(x_all.max())

    ceilings: list[float] = []
    g20s: list[float] = []
    g50s: list[float] = []

    n = len(grouped)
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        xs: FloatArray = x_all[idx]
        ys: FloatArray = y_all[idx]
        if len(np.unique(xs)) < 2:
            continue

        fam: ModelFamily = family
        params: ModelParams | None

        if fam == "power":
            pp = _power_fit_grid(xs, ys)
            if pp is None:
                fam = "log"
                params = _log_fit(xs, ys)
            else:
                params = pp
        else:
            params = _log_fit(xs, ys)

        ceiling, g20, g50 = _estimate_from_model(fam, params, x_max=x_max, current=current, pcts=pcts)
        ceilings.append(float(np.clip(ceiling, 0.0, 1.0)))
        g20s.append(float(g20))
        g50s.append(float(g50))

    if not ceilings:
        ceilings = [float(min(1.0, current + 0.1))]
        g20s = [0.0]
        g50s = [0.0]

    def q20_80(arr: Sequence[float]) -> tuple[float, float]:
        a = np.asarray(arr, dtype=np.float64)
        lo, hi = np.quantile(a, [0.2, 0.8])
        return float(lo), float(hi)

    ceiling_range = q20_80(ceilings)
    g20_range = q20_80(g20s)
    g50_range = q20_80(g50s)

    def clamp_gain(r: tuple[float, float]) -> tuple[float, float]:
        lo, hi = r
        lo = max(lo, -0.02)
        hi = max(hi, lo)
        hi = min(hi, 1.0)
        return float(lo), float(hi)

    ceiling_range = (max(ceiling_range[0], current), max(ceiling_range[1], current))
    ceiling_range = (float(np.clip(ceiling_range[0], 0.0, 1.0)), float(np.clip(ceiling_range[1], 0.0, 1.0)))
    return ceiling_range, clamp_gain(g20_range), clamp_gain(g50_range)


def _confidence_score(
    grouped: Sequence[_GroupedX],
    fit_quality: FitQuality,
    std_at_max_x: float,
) -> tuple[float, list[str]]:
    n_unique_x = len(grouped)
    assumptions = ["Heuristic engine v1"]

    if n_unique_x <= 0:
        c = 0.0
    else:
        c = 0.2 + 0.15 * max(0, n_unique_x - 2)
        c = min(c, 0.9)

    if fit_quality == "weak":
        c -= 0.15
    elif fit_quality == "bad":
        c -= 0.30
    elif fit_quality == "insufficient_data":
        c -= 0.40

    has_repeats = any(g.count >= 2 for g in grouped)
    has_many_repeats = any(g.count >= 3 for g in grouped)
    if has_repeats:
        c += 0.05
    if has_many_repeats:
        c += 0.05

    if std_at_max_x > 0.06:
        c -= 0.20
    elif std_at_max_x > 0.03:
        c -= 0.10

    c = float(np.clip(c, 0.0, 1.0))
    if c < 0.6:
        assumptions.append("Requires more runs for stronger claims")
    return c, assumptions


def _std_stats(grouped: Sequence[_GroupedX]) -> tuple[float, float]:
    if not grouped:
        return 0.0, 0.0
    stds = np.asarray([g.y_std for g in grouped], dtype=np.float64)
    return float(stds.mean()), float(stds.max())


def _regime_from_signals(
    grouped: Sequence[_GroupedX],
    fit: FitReport,
    current: float,
    pcts: tuple[float, float],
) -> tuple[Regime, float, list[RegimeSignal]]:
    signals: list[RegimeSignal] = []
    n_unique_x = len(grouped)
    std_mean, std_max = _std_stats(grouped)
    x_span = float(grouped[-1].x / grouped[0].x) if n_unique_x >= 2 and grouped[0].x > 0 else 1.0

    signals.append(RegimeSignal(name="n_unique_x", value=n_unique_x, why="More unique x increases evidence."))
    signals.append(RegimeSignal(name="x_span", value=round(x_span, 6), why="Coverage across x-range."))
    signals.append(
        RegimeSignal(
            name="std_at_max_x",
            value=round(grouped[-1].y_std if grouped else 0.0, 6),
            why="Noise at current operating point.",
        )
    )
    signals.append(RegimeSignal(name="std_mean", value=round(std_mean, 6), why="Overall variability."))
    signals.append(RegimeSignal(name="fit_quality", value=fit.fit_quality, why="Fit reliability."))
    if fit.sanity.violations:
        signals.append(
            RegimeSignal(
                name="monotonic_violations",
                value=len(fit.sanity.violations),
                why="Non-monotonicity weakens data-size/budget learning curve assumptions.",
            )
        )

    if n_unique_x < 3 or fit.fit_quality in {"bad", "insufficient_data"}:
        return "UNKNOWN", 0.2, signals

    x_max = grouped[-1].x
    slope_gain_20: float

    if fit.model_family in {"log", "power"}:
        fam: ModelFamily = cast(ModelFamily, fit.model_family)
        x: FloatArray = np.asarray([g.x for g in grouped], dtype=np.float64)
        y: FloatArray = np.asarray([g.y_mean for g in grouped], dtype=np.float64)
        if fam == "power":
            params = _power_fit_grid(x, y)
        else:
            params = _log_fit(x, y)

        ceiling, g20, _ = _estimate_from_model(fam, params, x_max=x_max, current=current, pcts=pcts)
        slope_gain_20 = g20
        signals.append(
            RegimeSignal(
                name="slope_gain_at_max_x_+20%",
                value=round(float(slope_gain_20), 6),
                why="Expected marginal gain from increasing x near current max.",
            )
        )
        signals.append(
            RegimeSignal(
                name="ceiling_point_estimate",
                value=round(float(ceiling), 6),
                why="Ceiling proxy used by v1 (family-dependent).",
            )
        )
    else:
        dy = grouped[-1].y_mean - grouped[-2].y_mean
        dx_log = math.log(grouped[-1].x) - math.log(grouped[-2].x)
        slope_gain_20 = (dy / dx_log) * math.log(1.2) if dx_log > 1e-12 else 0.0
        signals.append(
            RegimeSignal(
                name="slope_gain_at_max_x_+20%",
                value=round(float(slope_gain_20), 6),
                why="Finite-difference slope proxy on log-x scale.",
            )
        )

    if std_max >= 0.07 or std_mean >= 0.05:
        return "NOISE_LIMITED", 0.6, signals

    if slope_gain_20 >= 0.02 and std_mean < 0.03:
        return "DATA_LIMITED", 0.65, signals

    if slope_gain_20 <= 0.005 and std_mean < 0.03:
        return "MODEL_LIMITED", 0.65, signals

    if len(fit.sanity.violations) >= 2 and std_mean >= 0.04:
        return "OPTIMIZATION_LIMITED", 0.5, signals

    return "UNKNOWN", 0.35, signals


def _limiting_factors(regime: Regime) -> list[str]:
    mapping: dict[Regime, list[str]] = {
        "DATA_LIMITED": ["data_quantity_or_budget"],
        "MODEL_LIMITED": ["model_capacity_or_features"],
        "NOISE_LIMITED": ["evaluation_noise_or_instability"],
        "OPTIMIZATION_LIMITED": ["training_instability_or_hyperparameters"],
        "UNKNOWN": ["unknown"],
    }
    return mapping[regime]


def analyze_saturation(
    run_points: list[RunPoint] | list[dict],
    *,
    pcts: tuple[float, float] = (0.2, 0.5),
    n_boot: int = 200,
    rng_seed: int = 0,
) -> tuple[SaturationEstimate, RegimeEstimate, DataPotentialDraft]:
    """Analyze learning/saturation with transparent heuristics.

    Returns:
      (SaturationEstimate, RegimeEstimate, DataPotentialDraft)
    """

    pts = _coerce_run_points(run_points)
    if not pts:
        raise ValueError("no valid run_points after preprocessing")

    evidence_run_ids = [p.run_id for p in pts]
    grouped = _group_by_x(pts)

    current = grouped[-1].y_mean
    std_at_max_x = grouped[-1].y_std

    violations = _monotonic_violations(grouped)

    coverage = FitCoverage(
        n_points=len(pts),
        n_unique_x=len(grouped),
        x_min=float(grouped[0].x),
        x_max=float(grouped[-1].x),
    )

    if len(grouped) < 3:
        fit = FitReport(
            model_family="none",
            fit_quality="insufficient_data",
            mae=None,
            r2=None,
            coverage=coverage,
            sanity=FitSanity(monotonic_expected=True, violations=violations),
        )
        conf, assumptions = _confidence_score(grouped, "insufficient_data", std_at_max_x)
        assumptions.append(
            "Insufficient coverage: ceiling_range uses default +0.10 headroom placeholder (not evidence-based)."
        )

        ceiling_range = (float(current), float(min(1.0, current + 0.10)))
        sat = SaturationEstimate(
            ceiling_range=ceiling_range,
            marginal_gain_p20_range=(0.0, 0.0),
            marginal_gain_p50_range=(0.0, 0.0),
            confidence=conf,
            assumptions=assumptions,
            evidence_run_ids=evidence_run_ids,
            fit=fit,
        )
        regime, r_conf, signals = _regime_from_signals(grouped, fit, current=current, pcts=pcts)
        regime_est = RegimeEstimate(
            regime=regime,
            confidence=float(np.clip(min(conf, r_conf), 0.0, 1.0)),
            signals=signals,
            evidence_run_ids=evidence_run_ids,
        )
        draft = DataPotentialDraft(
            current=float(np.clip(current, 0.0, 1.0)),
            low=float(np.clip(ceiling_range[0], 0.0, 1.0)),
            high=float(np.clip(ceiling_range[1], 0.0, 1.0)),
            confidence=sat.confidence,
            limiting_factors=_limiting_factors(regime_est.regime),
            assumptions=sat.assumptions,
            evidence={"run_ids": evidence_run_ids},
        )
        return sat, regime_est, draft

    family, _, _, mae, r2v, model_violations = _choose_model(grouped)
    fit_quality: FitQuality = _fit_quality(mae, r2v)
    if family == "none":
        fit_quality = "bad"

    if model_violations:
        violations = [*violations, *model_violations]

    fit = FitReport(
        model_family=family,
        fit_quality=fit_quality,
        mae=mae,
        r2=r2v,
        coverage=coverage,
        sanity=FitSanity(monotonic_expected=True, violations=violations),
    )

    conf, assumptions = _confidence_score(grouped, fit_quality, std_at_max_x)

    rng = np.random.default_rng(rng_seed)
    ceiling_range, g20_range, g50_range = _bootstrap_ranges(
        grouped,
        family=family if family != "none" else "log",
        pcts=pcts,
        n_boot=n_boot,
        rng=rng,
        current=current,
    )

    if family == "log":
        assumptions.append("Log model has no asymptotic ceiling; ceiling is a 10x-xmax projection")
    if family == "none" or fit_quality == "bad":
        assumptions.append("No reliable functional fit; ranges are conservative")

    sat = SaturationEstimate(
        ceiling_range=ceiling_range,
        marginal_gain_p20_range=g20_range,
        marginal_gain_p50_range=g50_range,
        confidence=conf,
        assumptions=assumptions,
        evidence_run_ids=evidence_run_ids,
        fit=fit,
    )

    regime, r_conf, signals = _regime_from_signals(grouped, fit, current=current, pcts=pcts)
    regime_est = RegimeEstimate(
        regime=regime,
        confidence=float(np.clip(min(conf, r_conf), 0.0, 1.0)),
        signals=signals,
        evidence_run_ids=evidence_run_ids,
    )

    draft = DataPotentialDraft(
        current=float(np.clip(current, 0.0, 1.0)),
        low=float(np.clip(ceiling_range[0], 0.0, 1.0)),
        high=float(np.clip(ceiling_range[1], 0.0, 1.0)),
        confidence=sat.confidence,
        limiting_factors=_limiting_factors(regime_est.regime),
        assumptions=sat.assumptions,
        evidence={"run_ids": evidence_run_ids},
    )

    return sat, regime_est, draft