from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contracts.run_report import RunReportV1, RunReportV2
from store.repository import (
    DiagnosticSignalPointCreateData,
    MetricPointCreateData,
    Repository,
    RunCreateData,
)
from use_cases.transitions import ForbiddenTransitionError

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class RunReportIngestResult:
    run_id: str
    external_run_id: str
    created: bool


def ingest_run_report_in_session(
    repo: Repository,
    s: Session,
    tenant_id: str,
    report: RunReportV1 | RunReportV2,
) -> RunReportIngestResult:
    """Create a Run and child points from a RunReport, or return the existing Run.

    The idempotency key is (tenant_id, external_run_id). Store remains persistence-only;
    the use-case owns the rule that an existing external run must not create duplicate
    metric_points or diagnostic_signals.
    """

    existing = repo.get_run_by_external_run_id_in_session(s, tenant_id, report.external_run_id)
    if existing is not None:
        return RunReportIngestResult(
            run_id=str(existing.id),
            external_run_id=str(existing.external_run_id),
            created=False,
        )

    now = _utcnow_naive()
    run_id = str(uuid4())
    run_meta = report.run
    run = repo.create_run_in_session(
        s,
        tenant_id,
        RunCreateData(
            id=run_id,
            external_run_id=report.external_run_id,
            created_at=run_meta.started_at.replace(tzinfo=None) if run_meta.started_at else now,
            updated_at=now,
            status=run_meta.status,
            dataset_version=run_meta.dataset_version,
            dataset_size=run_meta.dataset_size,
            model_tag=run_meta.model_tag,
            seed=run_meta.seed,
            budget_kind=run_meta.budget_kind,
            budget_value=run_meta.budget_value,
            metric_name=run_meta.metric_name,
            split=run_meta.split,
            metric_final=run_meta.metric_final,
            config_hash=run_meta.config_hash,
            git_commit=run_meta.git_commit,
        ),
    )
    points = [
        MetricPointCreateData(
            id=str(uuid4()),
            series_name=point.series_name,
            x_kind=point.x_kind,
            x_value=point.x_value,
            y_value=point.y_value,
            created_at=now,
        )
        for point in report.metric_points
    ]
    repo.create_metric_points_in_session(s, tenant_id, run.id, points)

    if isinstance(report, RunReportV2) and report.diagnostic_signals:
        diag_data = [
            DiagnosticSignalPointCreateData(
                id=str(uuid4()),
                series_name=point.series_name,
                x_kind=point.x_kind,
                x_value=point.x_value,
                y_value=point.y_value,
                created_at=now,
            )
            for point in report.diagnostic_signals
        ]
        repo.create_diagnostic_signal_points_in_session(s, tenant_id, run.id, diag_data)

    return RunReportIngestResult(
        run_id=str(run.id),
        external_run_id=str(run.external_run_id),
        created=True,
    )


def ingest_run_report_use_case(
    repo: Repository,
    tenant_id: str,
    report: RunReportV1 | RunReportV2,
) -> RunReportIngestResult:
    try:
        with repo.session() as s:
            result = ingest_run_report_in_session(repo, s, tenant_id, report)
    except IntegrityError as exc:
        with repo.read_session() as s:
            existing = repo.get_run_by_external_run_id_in_session(
                s,
                tenant_id,
                report.external_run_id,
            )
            if existing is not None:
                return RunReportIngestResult(
                    run_id=str(existing.id),
                    external_run_id=str(existing.external_run_id),
                    created=False,
                )
        raise ForbiddenTransitionError("Duplicate external_run_id") from exc

    # Best-effort auto-diagnosis after successful ingest of a newly created run.
    # Mirrors the pattern in use_cases.jobs.complete_job: diagnosis runs OUTSIDE
    # the ingest transaction, swallows all exceptions, and never fails the request.
    # Skip on idempotent re-ingest (created=False) to avoid re-running diagnosis
    # whenever a duplicate report is replayed.
    if result.created:
        try:
            from use_cases.diagnostics import diagnose_and_store_run_use_case

            diagnose_and_store_run_use_case(repo, tenant_id, result.run_id)
        except Exception:  # noqa: BLE001
            logger.warning(
                "auto-diagnosis failed for tenant_id=%s run_id=%s",
                tenant_id,
                result.run_id,
                exc_info=True,
            )

    return result