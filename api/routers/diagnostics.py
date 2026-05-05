from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from api.deps import get_repo, get_tenant_id
from api.schemas.diagnostics import DiagnosisReportRead
from use_cases.diagnostics import (
    diagnose_and_store_run_use_case,
    diagnose_run_use_case,
    get_stored_diagnosis_use_case,
    list_diagnosis_history_use_case,
)

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[Any, Depends(get_repo)]


def _to_dto(report: Any) -> DiagnosisReportRead:
    return DiagnosisReportRead.model_validate(report.model_dump())


@router.get("/runs/{run_id}", response_model=DiagnosisReportRead)
def get_diagnostics_for_run(
    run_id: str,
    tenant_id: TenantId,
    repo: RepoDep,
    force_recompute: bool = False,
) -> DiagnosisReportRead:
    if force_recompute:
        report = diagnose_run_use_case(repo, tenant_id, run_id)
        return _to_dto(report)

    stored = get_stored_diagnosis_use_case(repo, tenant_id, run_id)
    if stored is not None:
        return _to_dto(stored)

    report = diagnose_run_use_case(repo, tenant_id, run_id)
    return _to_dto(report)


@router.get("/runs/{run_id}/history", response_model=list[DiagnosisReportRead])
def list_diagnostics_history(
    run_id: str,
    tenant_id: TenantId,
    repo: RepoDep,
) -> list[DiagnosisReportRead]:
    reports = list_diagnosis_history_use_case(repo, tenant_id, run_id)
    return [_to_dto(r) for r in reports]


@router.post("/runs/{run_id}:rediagnose", response_model=DiagnosisReportRead)
def rediagnose_run(
    run_id: str,
    tenant_id: TenantId,
    repo: RepoDep,
) -> DiagnosisReportRead:
    report = diagnose_and_store_run_use_case(repo, tenant_id, run_id)
    return _to_dto(report)
