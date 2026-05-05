from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.deps import get_repo, get_tenant_id
from api.schemas.run import RunCreate, RunRead
from api.schemas.run_report import RunReportIngestResponse, RunReportPayload
from use_cases.run_reports import ingest_run_report_use_case
from use_cases.runs import create_run_use_case

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[Any, Depends(get_repo)]

Limit = Annotated[int, Query(ge=1, le=500)]
Offset = Annotated[int, Query(ge=0)]


def _row_to_read(row: Any) -> RunRead:
    return RunRead(
        id=str(row.id),
        created_at=row.created_at,
        updated_at=row.updated_at,
        status=str(row.status),
        dataset_version=(str(row.dataset_version) if row.dataset_version is not None else None),
        dataset_size=float(row.dataset_size),
        model_tag=str(row.model_tag),
        seed=(int(row.seed) if row.seed is not None else None),
        budget_kind=str(row.budget_kind),
        budget_value=float(row.budget_value),
        metric_name=str(row.metric_name),
        split=(str(row.split) if row.split is not None else None),
        metric_final=float(row.metric_final),
        config_hash=(str(row.config_hash) if row.config_hash is not None else None),
        git_commit=(str(row.git_commit) if row.git_commit is not None else None),
    )


@router.post("", response_model=RunRead, status_code=status.HTTP_201_CREATED)
def create_run(payload: RunCreate, tenant_id: TenantId, repo: RepoDep) -> RunRead:
    row = create_run_use_case(repo, tenant_id, payload.model_dump(exclude_none=True))
    return _row_to_read(row)


@router.post("/ingest", response_model=RunReportIngestResponse)
def ingest_run_report(
    payload: RunReportPayload,
    tenant_id: TenantId,
    repo: RepoDep,
) -> RunReportIngestResponse:
    result = ingest_run_report_use_case(repo, tenant_id, payload)
    return RunReportIngestResponse(
        run_id=result.run_id,
        external_run_id=result.external_run_id,
        created=result.created,
    )


@router.get("", response_model=list[RunRead])
def list_runs(
    tenant_id: TenantId,
    repo: RepoDep,
    limit: Limit = 200,
    offset: Offset = 0,
    model_tag: str | None = None,
    dataset_version: str | None = None,
    metric_name: str | None = None,
    split: str | None = None,
    budget_kind: str | None = None,
) -> list[RunRead]:
    rows = repo.list_runs(
        tenant_id,
        model_tag=model_tag,
        dataset_version=dataset_version,
        metric_name=metric_name,
        split=split,
        budget_kind=budget_kind,
        limit=limit,
        offset=offset,
    )
    return [_row_to_read(r) for r in rows]


@router.get("/{run_id}", response_model=RunRead)
def get_run(run_id: str, tenant_id: TenantId, repo: RepoDep) -> RunRead:
    row = repo.get_run(tenant_id, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _row_to_read(row)
