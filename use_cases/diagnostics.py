from __future__ import annotations

from analytics_engine.diagnostics_schemas import DiagnosisReport, DiagnosticsInput
from analytics_engine.diagnostics_v1 import diagnose
from store.repository import Repository
from use_cases.archive import NotFoundError

# Pick exactly ONE x_kind: prefer epoch, then step, then time.
_X_KIND_PRIORITY: tuple[str, ...] = ("epoch", "step", "time")


def diagnose_run_use_case(
    repo: Repository,
    tenant_id: str,
    run_id: str,
) -> DiagnosisReport:
    """Build a DiagnosticsInput from a single run and run v1 detectors.

    - Loads the run; raises NotFoundError if missing in this tenant.
    - Loads metric points; uses only series_name in {"val","train"}.
    - Picks one consistent x_kind by priority: epoch > step > time, based on
      which kinds are present for the val series.
    - Never mixes different x_kind values inside the same DiagnosticsInput.
    - No detector logic lives here.
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

    if chosen_x_kind is None:
        val_series: list[tuple[float, float]] = []
        train_series: list[tuple[float, float]] = []
    else:
        val_series = sorted(
            (
                (float(p.x_value), float(p.y_value))
                for p in points
                if p.series_name == "val" and p.x_kind == chosen_x_kind
            ),
            key=lambda t: t[0],
        )
        train_series = sorted(
            (
                (float(p.x_value), float(p.y_value))
                for p in points
                if p.series_name == "train" and p.x_kind == chosen_x_kind
            ),
            key=lambda t: t[0],
        )

    inp = DiagnosticsInput(
        run_id=str(run.id),
        metric_name=str(run.metric_name),
        val_series=val_series,
        train_series=train_series,
    )
    return diagnose(inp)
