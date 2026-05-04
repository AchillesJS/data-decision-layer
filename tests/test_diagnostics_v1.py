from __future__ import annotations

from collections.abc import Sequence

from analytics_engine.diagnostics_schemas import DiagnosticsInput
from analytics_engine.diagnostics_v1 import diagnose


def _input(
    val: Sequence[tuple[float, float]],
    *,
    train: Sequence[tuple[float, float]] | None = None,
    metric_name: str = "accuracy",
    run_id: str = "r1",
) -> DiagnosticsInput:
    return DiagnosticsInput(
        run_id=run_id,
        metric_name=metric_name,
        val_series=[(float(x), float(y)) for x, y in val],
        train_series=[(float(x), float(y)) for x, y in (train or [])],
    )


def _kinds(report) -> list[str]:
    return [f.kind for f in report.findings]


# ---------------------------------------------------------------------------
# Short-circuit branches
# ---------------------------------------------------------------------------


def test_insufficient_data_returns_single_finding() -> None:
    inp = _input([(1, 0.5), (2, 0.55), (3, 0.6)])
    report = diagnose(inp)
    assert len(report.findings) == 1
    assert report.findings[0].kind == "insufficient_data"
    assert report.findings[0].severity == "info"
    assert report.assumptions  # heuristic-v1 assumption present


def test_invalid_series_returns_single_finding() -> None:
    val = [(1, 0.4), (2, 0.5), (1, 0.6), (3, 0.7), (4, 0.8)]
    report = diagnose(_input(val))
    assert len(report.findings) == 1
    assert report.findings[0].kind == "invalid_series"
    assert report.findings[0].severity == "warn"


def test_unsupported_metric_scale_returns_single_finding() -> None:
    val = [(i, 1.0 / i) for i in range(1, 11)]
    report = diagnose(_input(val, metric_name="train_loss"))
    assert len(report.findings) == 1
    assert report.findings[0].kind == "unsupported_metric_scale"
    assert report.findings[0].severity == "info"


# ---------------------------------------------------------------------------
# Detector triggers
# ---------------------------------------------------------------------------


def test_cold_start_detected() -> None:
    val = [(i, 0.5) for i in range(1, 11)]  # completely flat
    kinds = _kinds(diagnose(_input(val)))
    assert "cold_start_failure" in kinds


def test_cold_start_not_triggered_when_learning() -> None:
    val = [(i, 0.30 + 0.05 * i) for i in range(1, 11)]  # +0.05 per step
    kinds = _kinds(diagnose(_input(val)))
    assert "cold_start_failure" not in kinds


def test_plateau_late_detected() -> None:
    val = [(1, 0.30), (2, 0.45), (3, 0.55), (4, 0.60), (5, 0.62), (6, 0.621), (7, 0.621), (8, 0.621)]
    report = diagnose(_input(val))
    assert "plateau_late" in _kinds(report)


def test_plateau_late_severity_info_when_high() -> None:
    val = [(1, 0.50), (2, 0.65), (3, 0.72), (4, 0.74), (5, 0.75), (6, 0.751), (7, 0.751), (8, 0.751)]
    report = diagnose(_input(val))
    plateau = next(f for f in report.findings if f.kind == "plateau_late")
    assert plateau.severity == "info"


def test_plateau_late_severity_warn_when_low() -> None:
    val = [(1, 0.30), (2, 0.40), (3, 0.50), (4, 0.55), (5, 0.56), (6, 0.561), (7, 0.561), (8, 0.561)]
    report = diagnose(_input(val))
    plateau = next(f for f in report.findings if f.kind == "plateau_late")
    assert plateau.severity == "warn"


def test_overfitting_divergence_detected() -> None:
    val = [(1, 0.50), (2, 0.55), (3, 0.58), (4, 0.59), (5, 0.59), (6, 0.59), (7, 0.59), (8, 0.59)]
    train = [(1, 0.52), (2, 0.60), (3, 0.68), (4, 0.78), (5, 0.84), (6, 0.88), (7, 0.91), (8, 0.93)]
    kinds = _kinds(diagnose(_input(val, train=train)))
    assert "overfitting_divergence" in kinds


def test_overfitting_skipped_without_train_series() -> None:
    val = [(1, 0.50), (2, 0.55), (3, 0.58), (4, 0.59), (5, 0.59), (6, 0.59), (7, 0.59), (8, 0.59)]
    kinds = _kinds(diagnose(_input(val)))
    assert "overfitting_divergence" not in kinds


def test_overfitting_severity_critical_when_large_gap() -> None:
    val = [(1, 0.50), (2, 0.51), (3, 0.52), (4, 0.52), (5, 0.52), (6, 0.52), (7, 0.52), (8, 0.52)]
    train = [(1, 0.51), (2, 0.55), (3, 0.65), (4, 0.75), (5, 0.85), (6, 0.92), (7, 0.96), (8, 0.99)]
    f = next(
        x for x in diagnose(_input(val, train=train)).findings
        if x.kind == "overfitting_divergence"
    )
    assert f.severity == "critical"


def test_late_collapse_detected_warn() -> None:
    val = [(1, 0.40), (2, 0.55), (3, 0.65), (4, 0.70), (5, 0.72), (6, 0.71), (7, 0.69)]
    f = next(x for x in diagnose(_input(val)).findings if x.kind == "late_collapse")
    assert f.severity == "warn"


def test_late_collapse_detected_critical() -> None:
    val = [(1, 0.40), (2, 0.55), (3, 0.65), (4, 0.75), (5, 0.80), (6, 0.78), (7, 0.70)]
    f = next(x for x in diagnose(_input(val)).findings if x.kind == "late_collapse")
    assert f.severity == "critical"


def test_high_variance_detected() -> None:
    val = [(1, 0.40), (2, 0.45), (3, 0.50), (4, 0.30), (5, 0.65), (6, 0.40), (7, 0.70), (8, 0.42)]
    kinds = _kinds(diagnose(_input(val)))
    assert "high_variance" in kinds


def test_train_underfitting_detected() -> None:
    val = [(1, 0.30), (2, 0.32), (3, 0.34), (4, 0.36), (5, 0.37), (6, 0.38), (7, 0.39), (8, 0.40)]
    train = [(1, 0.33), (2, 0.36), (3, 0.40), (4, 0.42), (5, 0.42), (6, 0.421), (7, 0.421), (8, 0.421)]
    kinds = _kinds(diagnose(_input(val, train=train)))
    assert "train_underfitting" in kinds


def test_premature_saturation_detected() -> None:
    val = [
        (1, 0.50),
        (2, 0.501),
        (3, 0.502),
        (4, 0.503),
        (5, 0.504),
        (6, 0.505),
        (7, 0.506),
        (8, 0.507),
        (9, 0.508),
        (10, 0.509),
    ]
    kinds = _kinds(diagnose(_input(val)))
    assert "premature_saturation" in kinds


def test_orchestrator_sorts_by_severity() -> None:
    # Construct a curve that emits cold_start (critical) + plateau_late (warn) + premature_saturation (info).
    val = [(i, 0.5) for i in range(1, 11)]
    report = diagnose(_input(val))
    severities = [f.severity for f in report.findings]
    rank = {"critical": 0, "warn": 1, "info": 2}
    assert severities == sorted(severities, key=lambda s: rank[s])
    assert {"cold_start_failure", "plateau_late", "premature_saturation"}.issubset(
        {f.kind for f in report.findings}
    )
