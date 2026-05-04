from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from api.deps import get_repo, get_tenant_id
from api.schemas.diagnostics import DiagnosisReportRead
from use_cases.diagnostics import diagnose_run_use_case

router = APIRouter(prefix="/api/v1/diagnostics", tags=["diagnostics"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[Any, Depends(get_repo)]


@router.get("/runs/{run_id}", response_model=DiagnosisReportRead)
def get_diagnostics_for_run(
    run_id: str,
    tenant_id: TenantId,
    repo: RepoDep,
) -> DiagnosisReportRead:
    report = diagnose_run_use_case(repo, tenant_id, run_id)
    return DiagnosisReportRead.model_validate(report.model_dump())
