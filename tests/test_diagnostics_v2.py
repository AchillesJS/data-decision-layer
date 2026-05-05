from __future__ import annotations

import math

from analytics_engine.diagnostics_full import diagnose_full
from analytics_engine.diagnostics_schemas import DiagnosticsInput, Finding
from analytics_engine.diagnostics_v2 import (
    V2_GRAD_EXPLODE_ABS,
    V2_GRAD_EXPLODE_SPIKE_MULT,
    V2_GRAD_VANISH_GEOMEAN,
    V2_LR_HIGH_OSC_SIGN_CHANGES,
    V2_WEIGHT_EXPLOSION_MULT,
    detect_exploding_gradient,
    detect_gradient_norm_decay,
    detect_learning_rate_too_high,
    detect_learning_rate_too_low,
    detect_vanishing_gradient,
    detect_weight_norm_explosion,
    run_v2_detectors,
)


def _kinds(report) -> list[str]:
    return [f.kind for f in report.findings]


def _learning_curve_input() -> DiagnosticsInput:
    val = [(float(i), 0.30 + 0.05 * i) for i in range(1, 11)]
    train = [(float(i), 0.32 + 0.05 * i) for i in range(1, 11)]
    return DiagnosticsInput(
        run_id="r1",
        metric_name="accuracy",
        val_series=val,
        train_series=train,
    )


# ---------------------------------------------------------------------------
# Detector unit tests
# ---------------------------------------------------------------------------


def test_vanishing_gradient_detected() -> None:
    tiny = V2_GRAD_VANISH_GEOMEAN / 10.0
    signals = {
        "grad_norm_global": [(float(i), tiny) for i in range(1, 11)],
    }
    f = detect_vanishing_gradient(signals)
    assert f is not None
    assert f.kind == "vanishing_gradient"
    assert f.severity == "critical"


def test_exploding_gradient_detected_by_max() -> None:
    pts = [(float(i), 5.0) for i in range(1, 10)]
    pts.append((10.0, V2_GRAD_EXPLODE_ABS * 2.0))
    signals = {"grad_norm_global": pts}
    f = detect_exploding_gradient(signals)
    assert f is not None
    assert f.kind == "exploding_gradient"
    assert f.severity == "critical"


def test_exploding_gradient_detected_by_spike() -> None:
    median_val = 1.0
    pts = [(float(i), median_val) for i in range(1, 10)]
    spike = V2_GRAD_EXPLODE_SPIKE_MULT * median_val * 5.0
    assert spike < V2_GRAD_EXPLODE_ABS  # spike branch only
    pts.append((10.0, spike))
    signals = {"grad_norm_global": pts}
    f = detect_exploding_gradient(signals)
    assert f is not None
    assert f.kind == "exploding_gradient"


def test_gradient_norm_decay_warn() -> None:
    pts = [(float(i), math.exp(-1.0 * i)) for i in range(1, 11)]
    signals = {"grad_norm_global": pts}
    f = detect_gradient_norm_decay(signals)
    assert f is not None
    assert f.kind == "gradient_norm_decay"
    assert f.severity == "warn"


def test_lr_too_high_with_oscillating_loss() -> None:
    lr = [(float(i), 0.1) for i in range(1, 11)]
    # Oscillating loss in last half: 1.0, 1.6, 0.9, 1.5, 1.0
    loss = [
        (1.0, 2.0),
        (2.0, 1.5),
        (3.0, 1.2),
        (4.0, 1.4),
        (5.0, 1.0),
        (6.0, 1.6),
        (7.0, 0.9),
        (8.0, 1.5),
        (9.0, 1.0),
        (10.0, 1.7),
    ]
    f = detect_learning_rate_too_high({"lr": lr, "loss_train": loss})
    assert f is not None
    assert f.kind == "learning_rate_too_high"
    assert f.severity == "warn"
    assert int(f.evidence["sign_changes_last_half"]) >= V2_LR_HIGH_OSC_SIGN_CHANGES


def test_lr_too_low_with_shallow_loss_decay() -> None:
    lr = [(float(i), 1e-5) for i in range(1, 11)]
    # Loss decreases very slowly: from 2.0 to ~1.998
    loss = [(float(i), 2.0 - 0.0002 * i) for i in range(1, 11)]
    f = detect_learning_rate_too_low({"lr": lr, "loss_train": loss})
    assert f is not None
    assert f.kind == "learning_rate_too_low"
    assert f.severity == "info"


def test_weight_norm_explosion_detected() -> None:
    # initial 1.0, final clearly above V2_WEIGHT_EXPLOSION_MULT * initial
    pts = [(1.0, 1.0), (2.0, 1.5), (3.0, 3.0), (4.0, V2_WEIGHT_EXPLOSION_MULT * 2.0)]
    f = detect_weight_norm_explosion({"weight_norm_global": pts})
    assert f is not None
    assert f.kind == "weight_norm_explosion"
    assert f.severity == "warn"


def test_v2_detectors_skip_when_signal_missing() -> None:
    # Only val/train curves, no diagnostic signals — no v2 finding allowed.
    findings = run_v2_detectors(None)
    assert findings == []
    findings = run_v2_detectors({})
    assert findings == []
    findings = run_v2_detectors({"unrelated_series": [(1.0, 1.0), (2.0, 1.0)]})
    assert findings == []


def test_diagnose_full_merges_v1_and_v2_findings() -> None:
    # Cold-start curve triggers v1 cold_start_failure (critical).
    val = [(float(i), 0.5) for i in range(1, 11)]
    inp = DiagnosticsInput(
        run_id="r1",
        metric_name="accuracy",
        val_series=val,
        train_series=[],
    )
    # And vanishing gradients trigger a v2 critical finding.
    tiny = V2_GRAD_VANISH_GEOMEAN / 10.0
    signals = {"grad_norm_global": [(float(i), tiny) for i in range(1, 11)]}

    report = diagnose_full(inp, diagnostic_signals=signals)
    kinds = _kinds(report)
    assert "cold_start_failure" in kinds
    assert "vanishing_gradient" in kinds

    severities = [f.severity for f in report.findings]
    rank = {"critical": 0, "warn": 1, "info": 2}
    assert severities == sorted(severities, key=lambda s: rank[s])


def test_series_was_reordered_extra_finding_is_preserved() -> None:
    inp = _learning_curve_input()
    extras = [
        Finding(
            kind="series_was_reordered",
            severity="info",
            title="Metric series was reordered",
            description="Metric points were not received in increasing x order and were reordered before diagnostics.",
            suggested_checks=["Check whether metric logging writes monotonically increasing epoch or step values."],
        )
    ]
    report = diagnose_full(inp, diagnostic_signals=None, extra_findings=extras)
    assert "series_was_reordered" in _kinds(report)


def test_diagnose_full_runs_v2_even_when_v1_short_circuits_on_insufficient_data() -> None:
    # Only 3 val points -> v1 short-circuits with insufficient_data.
    val = [(1.0, 0.4), (2.0, 0.5), (3.0, 0.6)]
    inp = DiagnosticsInput(
        run_id="r1",
        metric_name="accuracy",
        val_series=val,
        train_series=[],
    )
    tiny = V2_GRAD_VANISH_GEOMEAN / 10.0
    signals = {"grad_norm_global": [(float(i), tiny) for i in range(1, 11)]}

    report = diagnose_full(inp, diagnostic_signals=signals)
    kinds = _kinds(report)
    assert "insufficient_data" in kinds
    assert "vanishing_gradient" in kinds
