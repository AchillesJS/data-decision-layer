"""Phase 2 full-diagnostics orchestrator: composes v1 (curve) and v2 (signals).

Contract:
- v1 is always run first; if v1 returns a short-circuit finding
  (unsupported_metric_scale / invalid_series / insufficient_data) the v2
  detectors may still run when diagnostic_signals are provided.
- v2 detectors only run when diagnostic_signals are non-empty.
- extra_findings (e.g. series_was_reordered emitted by orchestration paths)
  are merged in as well.
- Output is sorted by severity (critical > warn > info), preserving stable
  order inside each severity bucket.

Engine version reported by this orchestrator: see ENGINE_VERSION_FULL.
"""

from __future__ import annotations

from analytics_engine.diagnostics_schemas import (
    DiagnosisReport,
    DiagnosticsInput,
    Finding,
)
from analytics_engine.diagnostics_v1 import ASSUMPTION_HEURISTIC_V1, diagnose
from analytics_engine.diagnostics_v2 import (
    ASSUMPTION_HEURISTIC_V2,
    DiagnosticSignals,
    run_v2_detectors,
)

ENGINE_VERSION_FULL = "v1.0+v2.0"

ASSUMPTION_FULL = (
    "Heuristic diagnostics v1/v2 — signals derived from metric curves and "
    "diagnostic series only."
)

_SEVERITY_ORDER: dict[str, int] = {"critical": 0, "warn": 1, "info": 2}


def diagnose_full(
    inp: DiagnosticsInput,
    diagnostic_signals: DiagnosticSignals | None = None,
    extra_findings: list[Finding] | None = None,
) -> DiagnosisReport:
    """Compose v1 curve diagnostics with v2 deep-signal diagnostics.

    Parameters
    ----------
    inp:
        Phase 1 DiagnosticsInput (val/train normalized quality curves).
    diagnostic_signals:
        Optional dict {series_name: list[(x_value, y_value)]} for v2 detectors.
    extra_findings:
        Optional findings injected by the caller (e.g. series_was_reordered).
    """

    v1_report = diagnose(inp)
    findings: list[Finding] = list(v1_report.findings)

    v2_findings = run_v2_detectors(diagnostic_signals)
    findings.extend(v2_findings)

    if extra_findings:
        findings.extend(extra_findings)

    findings.sort(key=lambda f: _SEVERITY_ORDER[f.severity])

    assumptions: list[str] = [ASSUMPTION_FULL]
    # Preserve traceability to the underlying heuristic versions.
    assumptions.append(ASSUMPTION_HEURISTIC_V1)
    if v2_findings:
        assumptions.append(ASSUMPTION_HEURISTIC_V2)

    return DiagnosisReport(
        run_id=inp.run_id,
        metric_name=inp.metric_name,
        n_val_points=v1_report.n_val_points,
        n_train_points=v1_report.n_train_points,
        findings=findings,
        assumptions=assumptions,
    )
