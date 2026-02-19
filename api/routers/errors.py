from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError

from api.deps import get_repo, get_tenant_id
from api.schemas.error import ErrorCreate, ErrorRead
from core.error import Error
from use_cases.errors import create_error_use_case

router = APIRouter(prefix="/api/v1/errors", tags=["errors"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[Any, Depends(get_repo)]

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]
StatusFilter = Annotated[str | None, Query()]
YTrueFilter = Annotated[str | None, Query()]
YPredFilter = Annotated[str | None, Query()]


def _row_to_read(row) -> ErrorRead:
    return ErrorRead(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        status=row.status,
        y_true=row.y_true,
        y_pred=row.y_pred,
        confidence=row.confidence,
        uncertainty=row.uncertainty,
        repeatability=row.repeatability,
        example_ref=row.example_ref,
        context=row.context or {},
    )


@router.post("", response_model=ErrorRead, status_code=status.HTTP_201_CREATED)
def create_error(payload: ErrorCreate, tenant_id: TenantId, repo: RepoDep) -> ErrorRead:
    try:
        err = Error(**payload.model_dump(exclude_none=True))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    row = create_error_use_case(repo, tenant_id, err)
    return _row_to_read(row)



@router.get("", response_model=list[ErrorRead])
def list_errors(
    tenant_id: TenantId,
    repo: RepoDep,
    limit: Limit = 50,
    offset: Offset = 0,
    status: StatusFilter = None,
    y_true: YTrueFilter = None,
    y_pred: YPredFilter = None,
) -> list[ErrorRead]:
    rows = repo.list_errors(
        tenant_id,
        limit=limit,
        offset=offset,
        status=status,
        y_true=y_true,
        y_pred=y_pred,
    )
    return [_row_to_read(r) for r in rows]


@router.get("/{error_id}", response_model=ErrorRead)
def get_error(error_id: str, tenant_id: TenantId, repo: RepoDep) -> ErrorRead:
    row = repo.get_error(tenant_id, error_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Error not found")
    return _row_to_read(row)
