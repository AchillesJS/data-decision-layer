from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from contracts.run_report import RunReportV1, RunReportV2
from store.models import JobLogChunkRow, JobRow
from store.repository import (
    DiagnosticSignalPointCreateData,
    JobCreateData,
    JobLogChunkCreateData,
    MetricPointCreateData,
    Repository,
    RunCreateData,
)
from use_cases.actions import UseCaseValidationError
from use_cases.archive import NotFoundError
from use_cases.diagnostics import diagnose_and_store_run_use_case
from use_cases.runners import authenticate_runner_in_session, hash_secret, verify_secret
from use_cases.transitions import ForbiddenTransitionError

logger = logging.getLogger("ddw.jobs")

LEASE_TTL_SECONDS = 300
_ALLOWED_COMPLETE_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED"}
_FORBIDDEN_ENV_PARTS = ("SECRET", "TOKEN", "KEY")
_MAX_LOG_CHUNK_LENGTH = 64_000


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _normalize_tags(tags: list[str] | None) -> list[str] | None:
    if tags is None:
        return None
    return sorted({str(tag).strip() for tag in tags if str(tag).strip()})


def _validate_env(env: dict[str, str] | None) -> dict[str, str] | None:
    if env is None:
        return None
    clean: dict[str, str] = {}
    for key, value in env.items():
        normalized_key = str(key)
        upper = normalized_key.upper()
        if any(part in upper for part in _FORBIDDEN_ENV_PARTS):
            raise UseCaseValidationError("env must not contain SECRET/TOKEN/KEY keys in Jobs v1")
        clean[normalized_key] = str(value)
    return clean


def _job_matches_runner(job: JobRow, runner_tags: list[str], tags_filter: list[str] | None) -> bool:
    runner_tag_set = set(runner_tags)
    requested = set(job.requested_tags_json or [])
    if not requested.issubset(runner_tag_set):
        return False
    if tags_filter:
        filter_set = set(_normalize_tags(tags_filter) or [])
        return filter_set.issubset(runner_tag_set)
    return True


def _validate_lease(job: JobRow, runner_id: str, lease_token: str, now: datetime) -> None:
    if job.status != "RUNNING":
        raise ForbiddenTransitionError("Job is not running")
    if job.runner_id != runner_id:
        raise ForbiddenTransitionError("Lease runner mismatch")
    if not job.lease_token_hash or not lease_token:
        raise ForbiddenTransitionError("Lease token is required")
    if not verify_secret(lease_token, job.lease_token_hash):
        raise ForbiddenTransitionError("Lease token is invalid")
    if job.lease_expires_at is None or job.lease_expires_at <= now:
        raise ForbiddenTransitionError("Lease is expired")


def _validate_log_chunks(chunks: list[dict[Any, Any]]) -> None:
    for chunk in chunks:
        text = str(chunk.get("chunk", ""))
        if len(text) > _MAX_LOG_CHUNK_LENGTH:
            raise UseCaseValidationError("log chunk exceeds 64000 characters")


@dataclass(frozen=True)
class ClaimedJob:
    job: JobRow
    lease_token: str
    lease_expires_at: datetime


def create_job(repo: Repository, tenant_id: str, payload: dict[Any, Any]) -> JobRow:
    command = str(payload.get("command") or "").strip()
    if not command:
        raise UseCaseValidationError("command is required")
    timeout = payload.get("timeout_sec")
    now = _utcnow_naive()
    data = JobCreateData(
        id=str(uuid4()),
        status="QUEUED",
        requested_tags_json=_normalize_tags(payload.get("requested_tags")),
        command=command,
        workdir=(str(payload["workdir"]) if payload.get("workdir") else None),
        env_json=_validate_env(payload.get("env")),
        timeout_sec=(int(timeout) if timeout is not None else None),
        created_at=now,
        updated_at=now,
    )
    return repo.create_job(tenant_id, data)


def list_jobs_use_case(
    repo: Repository,
    tenant_id: str,
    *,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[JobRow]:
    return repo.list_jobs(tenant_id, status=status, limit=limit, offset=offset)


def get_job_use_case(repo: Repository, tenant_id: str, job_id: str) -> JobRow:
    row = repo.get_job(tenant_id, job_id)
    if row is None:
        raise NotFoundError("Job not found")
    return row


def list_job_logs_use_case(
    repo: Repository,
    tenant_id: str,
    job_id: str,
    runner_id: str,
    token: str,
    lease_token: str,
    *,
    limit: int = 200,
) -> list[JobLogChunkRow]:
    now = _utcnow_naive()
    with repo.session() as s:
        try:
            authenticate_runner_in_session(repo, s, tenant_id, runner_id, token)
        except UseCaseValidationError as exc:
            raise ForbiddenTransitionError("Invalid runner token") from exc
        job = repo.get_job_in_session(s, tenant_id, job_id)
        if job is None:
            raise NotFoundError("Job not found")
        _validate_lease(job, runner_id, lease_token, now)
        rows = repo.list_job_log_chunks_in_session(s, tenant_id, job_id, limit=limit)
        for row in rows:
            s.expunge(row)
        return rows


def claim_job(
    repo: Repository,
    tenant_id: str,
    runner_id: str,
    token: str,
    *,
    tags_filter: list[str] | None = None,
) -> ClaimedJob | None:
    now = _utcnow_naive()
    with repo.session() as s:
        runner = authenticate_runner_in_session(repo, s, tenant_id, runner_id, token)
        runner.status = "ONLINE"
        runner.last_seen_at = now
        runner.updated_at = now
        for job in repo.list_queued_jobs_in_session(s, tenant_id):
            if not _job_matches_runner(job, runner.tags_json, tags_filter):
                continue
            lease_token = str(uuid4()) + str(uuid4())
            lease_expires_at = now + timedelta(seconds=LEASE_TTL_SECONDS)
            job.status = "RUNNING"
            job.runner_id = runner.id
            job.lease_token_hash = hash_secret(lease_token)
            job.lease_expires_at = lease_expires_at
            job.started_at = now
            job.updated_at = now
            s.flush()
            s.expunge(job)
            return ClaimedJob(job=job, lease_token=lease_token, lease_expires_at=lease_expires_at)
    return None


def append_logs(
    repo: Repository,
    tenant_id: str,
    job_id: str,
    runner_id: str,
    token: str,
    lease_token: str,
    chunks: list[dict[Any, Any]],
) -> None:
    _validate_log_chunks(chunks)
    now = _utcnow_naive()
    try:
        with repo.session() as s:
            authenticate_runner_in_session(repo, s, tenant_id, runner_id, token)
            job = repo.get_job_in_session(s, tenant_id, job_id)
            if job is None:
                raise NotFoundError("Job not found")
            _validate_lease(job, runner_id, lease_token, now)
            data = [
                JobLogChunkCreateData(
                    id=str(uuid4()),
                    seq=int(chunk["seq"]),
                    ts=chunk.get("ts") or now,
                    stream=str(chunk["stream"]),
                    chunk=str(chunk["chunk"]),
                )
                for chunk in chunks
            ]
            repo.create_job_log_chunks_in_session(s, tenant_id, job_id, data)
            job.updated_at = now
            s.flush()
    except IntegrityError as exc:
        raise ForbiddenTransitionError("Duplicate job log chunk sequence") from exc


def _create_or_get_run_from_report_in_session(
    repo: Repository,
    s: Session,
    tenant_id: str,
    report: RunReportV1 | RunReportV2,
) -> str:
    existing = repo.get_run_by_external_run_id_in_session(s, tenant_id, report.external_run_id)
    if existing is not None:
        return str(existing.id)

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
                series_name=p.series_name,
                x_kind=p.x_kind,
                x_value=p.x_value,
                y_value=p.y_value,
                created_at=now,
            )
            for p in report.diagnostic_signals
        ]
        repo.create_diagnostic_signal_points_in_session(s, tenant_id, run.id, diag_data)

    return str(run.id)


def complete_job(
    repo: Repository,
    tenant_id: str,
    job_id: str,
    runner_id: str,
    token: str,
    lease_token: str,
    *,
    status: str,
    exit_code: int | None,
    error_message: str | None,
    run_report: RunReportV1 | RunReportV2 | None,
) -> JobRow:
    if status not in _ALLOWED_COMPLETE_STATUSES:
        raise UseCaseValidationError("Invalid complete status")
    if status == "SUCCEEDED" and run_report is None:
        raise UseCaseValidationError("run_report is required when completing a job as SUCCEEDED")
    now = _utcnow_naive()
    completed_run_id: str | None = None
    completed_job: JobRow | None = None
    try:
        with repo.session() as s:
            authenticate_runner_in_session(repo, s, tenant_id, runner_id, token)
            job = repo.get_job_in_session(s, tenant_id, job_id)
            if job is None:
                raise NotFoundError("Job not found")
            _validate_lease(job, runner_id, lease_token, now)
            run_id = None
            if run_report is not None:
                run_id = _create_or_get_run_from_report_in_session(repo, s, tenant_id, run_report)
            job.status = status
            job.exit_code = exit_code
            job.error_message = error_message
            job.finished_at = now
            job.updated_at = now
            job.run_id = run_id or job.run_id
            s.flush()
            s.expunge(job)
            completed_job = job
            completed_run_id = run_id
    except IntegrityError as exc:
        raise ForbiddenTransitionError("Duplicate external_run_id or job log chunk sequence") from exc

    if completed_run_id is not None:
        try:
            diagnose_and_store_run_use_case(repo, tenant_id, completed_run_id)
        except Exception:  # noqa: BLE001 - best-effort, must not break job completion
            logger.warning(
                "auto-diagnosis failed for tenant_id=%s run_id=%s",
                tenant_id,
                completed_run_id,
                exc_info=True,
            )

    assert completed_job is not None  # guaranteed by successful session block
    return completed_job
