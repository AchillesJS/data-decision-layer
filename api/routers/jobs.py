from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status

from api.deps import get_repo, get_tenant_id
from api.schemas.jobs import (
    JobClaimRequest,
    JobClaimResponse,
    JobCompleteRequest,
    JobCompleteResponse,
    JobCreateRequest,
    JobLogChunkRead,
    JobRead,
    LogsAppendRequest,
)
from use_cases.jobs import (
    append_logs,
    claim_job,
    complete_job,
    create_job,
    get_job_use_case,
    list_job_logs_use_case,
    list_jobs_use_case,
)

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[Any, Depends(get_repo)]
RunnerId = Annotated[str, Header(alias="X-Runner-Id")]
RunnerToken = Annotated[str, Header(alias="X-Runner-Token")]
LeaseToken = Annotated[str, Header(alias="X-Lease-Token")]


def _job_to_read(row: Any) -> JobRead:
    return JobRead(
        id=str(row.id),
        status=str(row.status),
        requested_tags=(list(row.requested_tags_json) if row.requested_tags_json is not None else None),
        runner_id=(str(row.runner_id) if row.runner_id is not None else None),
        command=str(row.command),
        workdir=(str(row.workdir) if row.workdir is not None else None),
        env=(dict(row.env_json) if row.env_json is not None else None),
        timeout_sec=(int(row.timeout_sec) if row.timeout_sec is not None else None),
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        exit_code=(int(row.exit_code) if row.exit_code is not None else None),
        error_message=(str(row.error_message) if row.error_message is not None else None),
        run_id=(str(row.run_id) if row.run_id is not None else None),
    )


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create(payload: JobCreateRequest, tenant_id: TenantId, repo: RepoDep) -> JobRead:
    row = create_job(repo, tenant_id, payload.model_dump(exclude_none=True))
    return _job_to_read(row)


@router.get("", response_model=list[JobRead])
def list_all(
    tenant_id: TenantId,
    repo: RepoDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[JobRead]:
    return [
        _job_to_read(row)
        for row in list_jobs_use_case(
            repo, tenant_id, status=status_filter, limit=limit, offset=offset
        )
    ]


@router.post("/claim", response_model=JobClaimResponse | None)
def claim(
    payload: JobClaimRequest,
    tenant_id: TenantId,
    repo: RepoDep,
    x_runner_id: RunnerId,
    x_runner_token: RunnerToken,
    response: Response,
) -> JobClaimResponse | None:
    result = claim_job(
        repo,
        tenant_id,
        x_runner_id,
        x_runner_token,
        tags_filter=payload.tags_filter,
    )
    if result is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return JobClaimResponse(
        job=_job_to_read(result.job),
        lease_token=result.lease_token,
        lease_expires_at=result.lease_expires_at,
    )



@router.get("/{job_id}", response_model=JobRead)
def get(job_id: str, tenant_id: TenantId, repo: RepoDep) -> JobRead:
    return _job_to_read(get_job_use_case(repo, tenant_id, job_id))


@router.get("/{job_id}/logs", response_model=list[JobLogChunkRead])
def get_logs(
    job_id: str,
    tenant_id: TenantId,
    repo: RepoDep,
    x_runner_id: RunnerId,
    x_runner_token: RunnerToken,
    x_lease_token: LeaseToken,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[JobLogChunkRead]:
    rows = list_job_logs_use_case(
        repo,
        tenant_id,
        job_id,
        x_runner_id,
        x_runner_token,
        x_lease_token,
        limit=limit,
    )
    return [
        JobLogChunkRead(
            id=str(row.id),
            job_id=str(row.job_id),
            seq=int(row.seq),
            ts=row.ts,
            stream=str(row.stream),
            chunk=str(row.chunk),
        )
        for row in rows
    ]


@router.post("/{job_id}/logs:append", status_code=status.HTTP_204_NO_CONTENT)
def logs_append(
    job_id: str,
    payload: LogsAppendRequest,
    tenant_id: TenantId,
    repo: RepoDep,
    x_runner_id: RunnerId,
    x_runner_token: RunnerToken,
    x_lease_token: LeaseToken,
) -> None:
    append_logs(
        repo,
        tenant_id,
        job_id,
        x_runner_id,
        x_runner_token,
        x_lease_token,
        [chunk.model_dump() for chunk in payload.chunks],
    )


@router.post("/{job_id}/complete", response_model=JobCompleteResponse)
def complete(
    job_id: str,
    payload: JobCompleteRequest,
    tenant_id: TenantId,
    repo: RepoDep,
    x_runner_id: RunnerId,
    x_runner_token: RunnerToken,
    x_lease_token: LeaseToken,
) -> JobCompleteResponse:
    row = complete_job(
        repo,
        tenant_id,
        job_id,
        x_runner_id,
        x_runner_token,
        x_lease_token,
        status=payload.status,
        exit_code=payload.exit_code,
        error_message=payload.error_message,
        run_report=payload.run_report,
    )
    return JobCompleteResponse(job_id=str(row.id), status=str(row.status), run_id=row.run_id)
