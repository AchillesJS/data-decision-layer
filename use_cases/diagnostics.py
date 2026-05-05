from __future__ import annotations

from analytics_engine.diagnostics_full import (
    ENGINE_VERSION_FULL,
    diagnose_full,
)
from analytics_engine.diagnostics_schemas import (
    DiagnosisReport,
    DiagnosticsInput,
    Finding,
)
from store.repository import Repository
from use_cases.archive import NotFoundError

# Pick exactly ONE x_kind: prefer epoch, then step, then time.
_X_KIND_PRIORITY: tuple[str, ...] = ("epoch", "step", "time")

_SERIES_REORDERED_FINDING = Finding(
    kind="series_was_reordered",
    severity="info",
    title="Metric series was reordered",
    description=(
        "Metric points were not received in increasing x order and were "
        "reordered before diagnostics."
    ),
    suggested_checks=[
        "Check whether metric logging writes monotonically increasing epoch or step values.",
    ],
)


def _is_strictly_increasing_xs(values: list[float]) -> bool:
    return all(b > a for a, b in zip(values, values[1:], strict=False))


def _build_curve_series(
    points: list,
    series_name: str,
    chosen_x_kind: str | None,
) -> tuple[list[tuple[float, float]], bool]:
    """Return (sorted series, was_out_of_order) for the chosen x_kind.

    `was_out_of_order` is True when the raw x sequence (in DB insertion order)
    was not strictly increasing for this series. Sorting still happens so the
    engine can run; the orchestrator surfaces the reorder as an info finding.
    """

    if chosen_x_kind is None:
        return [], False

    raw: list[tuple[float, float]] = [
        (float(p.x_value), float(p.y_value))
        for p in points
        if p.series_name == series_name and p.x_kind == chosen_x_kind
    ]
    if not raw:
        return [], False

    raw_xs = [x for x, _ in raw]
    out_of_order = len(raw_xs) >= 2 and not _is_strictly_increasing_xs(raw_xs)
    sorted_series = sorted(raw, key=lambda t: t[0])
    return sorted_series, out_of_order


def _build_diagnostic_signals(
    signal_points: list,
) -> dict[str, list[tuple[float, float]]]:
    """Group diagnostic_signal_points into a {series_name: [(x, y)]} dict.

    Per series: pick the highest-priority x_kind that is present, sort by x.
    If no points exist for any preferred x_kind, the series is omitted.
    """

    grouped: dict[str, dict[str, list[tuple[float, float]]]] = {}
    for p in signal_points:
        grouped.setdefault(str(p.series_name), {}).setdefault(str(p.x_kind), []).append(
            (float(p.x_value), float(p.y_value))
        )

    out: dict[str, list[tuple[float, float]]] = {}
    for series_name, by_kind in grouped.items():
        chosen: str | None = None
        for kind in _X_KIND_PRIORITY:
            if kind in by_kind and by_kind[kind]:
                chosen = kind
                break
        if chosen is None:
            continue
        out[series_name] = sorted(by_kind[chosen], key=lambda t: t[0])
    return out


def diagnose_run_use_case(
    repo: Repository,
    tenant_id: str,
    run_id: str,
) -> DiagnosisReport:
    """Build a DiagnosticsInput from a single run and run v1+v2 diagnostics.

    - Loads the run; raises NotFoundError if missing in this tenant.
    - Loads metric points; uses only series_name in {"val","train"}.
    - Loads diagnostic_signal_points and builds the v2 signals dict.
    - Picks one consistent x_kind by priority epoch > step > time, based on
      which kinds are present for the val series.
    - Detects raw-order violations BEFORE sorting and surfaces them as a
      `series_was_reordered` finding (info).
    - Never mixes different x_kind values inside the same DiagnosticsInput.
    - No detector logic lives here.
    - Does not persist the report.
    """

    run = repo.get_run(tenant_id, run_id)
    if run is None:
        raise NotFoundError("Run not found")

    points = repo.list_metric_points(tenant_id, run_id)

    chosen_x_kind: str | None = None
    for x_kind in _X_KIND_PRIORITY:
        if any(p.series_name == "val" and p.x_kind == x_kind for p in points):
            chosen_x_kind = x_kind
            break

    val_series, val_out_of_order = _build_curve_series(points, "val", chosen_x_kind)
    train_series, train_out_of_order = _build_curve_series(points, "train", chosen_x_kind)

    extra_findings: list[Finding] = []
    if val_out_of_order or train_out_of_order:
        extra_findings.append(_SERIES_REORDERED_FINDING.model_copy())

    signal_rows = repo.list_diagnostic_signal_points_for_runs(tenant_id, [run_id])
    diagnostic_signals = _build_diagnostic_signals(signal_rows)

    inp = DiagnosticsInput(
        run_id=str(run.id),
        metric_name=str(run.metric_name),
        val_series=val_series,
        train_series=train_series,
    )
    return diagnose_full(
        inp,
        diagnostic_signals=diagnostic_signals or None,
        extra_findings=extra_findings or None,
    )


def _persist_report(
    repo: Repository,
    tenant_id: str,
    run_id: str,
    report: DiagnosisReport,
) -> None:
    findings_json = [f.model_dump() for f in report.findings]
    repo.upsert_diagnosis_report(
        tenant_id,
        run_id,
        ENGINE_VERSION_FULL,
        report.metric_name,
        int(report.n_val_points),
        int(report.n_train_points),
        findings_json,
        list(report.assumptions),
    )


def diagnose_and_store_run_use_case(
    repo: Repository,
    tenant_id: str,
    run_id: str,
) -> DiagnosisReport:
    """Compute a diagnosis report and upsert it into diagnosis_reports."""

    report = diagnose_run_use_case(repo, tenant_id, run_id)
    _persist_report(repo, tenant_id, run_id, report)
    return report


def get_stored_diagnosis_use_case(
    repo: Repository,
    tenant_id: str,
    run_id: str,
    engine_version: str | None = None,
) -> DiagnosisReport | None:
    """Return the stored diagnosis for a run, or None if not stored.

    If engine_version is None, returns the latest stored report by created_at.
    """

    run = repo.get_run(tenant_id, run_id)
    if run is None:
        raise NotFoundError("Run not found")

    row = repo.get_diagnosis_report(tenant_id, run_id, engine_version)
    if row is None:
        return None
    return _row_to_report(row)


def list_diagnosis_history_use_case(
    repo: Repository,
    tenant_id: str,
    run_id: str,
) -> list[DiagnosisReport]:
    """Return all stored diagnosis reports for a run (newest first)."""

    run = repo.get_run(tenant_id, run_id)
    if run is None:
        raise NotFoundError("Run not found")

    rows = repo.list_diagnosis_reports(tenant_id, run_id)
    return [_row_to_report(row) for row in rows]


def _row_to_report(row) -> DiagnosisReport:
    findings = [Finding.model_validate(f) for f in (row.findings_json or [])]
    return DiagnosisReport(
        run_id=str(row.run_id),
        metric_name=str(row.metric_name),
        n_val_points=int(row.n_val_points),
        n_train_points=int(row.n_train_points),
        findings=findings,
        assumptions=list(row.assumptions_json or []),
    )
