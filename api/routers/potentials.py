from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError

from api.deps import get_repo, get_tenant_id
from api.schemas.potential import DataPotentialCreate, DataPotentialRead
from core.potential import DataPotential
from use_cases.archive import archive_data_potential_use_case

router = APIRouter(prefix="/api/v1/potentials", tags=["potentials"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[Any, Depends(get_repo)]

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]
StatusFilter = Annotated[str | None, Query()]


def _row_to_read(row) -> DataPotentialRead:
    return DataPotentialRead(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        status=row.status,
        metric_name=row.metric_name,
        current=row.current,
        upper_bound_range=row.upper_bound_range,
        scenarios=row.scenarios or {},
        confidence=row.confidence,
        sample_size=row.sample_size,
        limiting_factors=list(row.limiting_factors or []),
        assumptions=list(row.assumptions or []),
        evidence_error_ids=list(row.evidence_error_ids or []),
        notes=row.notes,
    )


@router.post("", response_model=DataPotentialRead, status_code=status.HTTP_201_CREATED)
def create_potential(payload: DataPotentialCreate, tenant_id: TenantId, repo: RepoDep) -> DataPotentialRead:
    try:
        potential = DataPotential(**payload.model_dump(exclude_none=True))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    repo.create_data_potential(tenant_id, potential)

    row = repo.get_data_potential(tenant_id, str(potential.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Potential not found")
    return _row_to_read(row)


@router.get("", response_model=list[DataPotentialRead])
def list_potentials(
    tenant_id: TenantId,
    repo: RepoDep,
    response: Response,
    limit: Limit = 50,
    offset: Offset = 0,
    status: StatusFilter = None,
) -> list[DataPotentialRead]:
    total = repo.count_data_potentials(tenant_id, status=status)
    response.headers["X-Total-Count"] = str(total)

    rows = repo.list_data_potentials(tenant_id, limit=limit, offset=offset, status=status)
    return [_row_to_read(r) for r in rows]


@router.get("/{potential_id}", response_model=DataPotentialRead)
def get_potential(potential_id: str, tenant_id: TenantId, repo: RepoDep) -> DataPotentialRead:
    row = repo.get_data_potential(tenant_id, potential_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Potential not found")
    return _row_to_read(row)


@router.post("/{potential_id}/archive", response_model=DataPotentialRead)
def archive_potential(potential_id: str, tenant_id: TenantId, repo: RepoDep) -> DataPotentialRead:
    archive_data_potential_use_case(repo, tenant_id, potential_id)

    row = repo.get_data_potential(tenant_id, potential_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Potential not found")
    return _row_to_read(row)
