from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError

from api.deps import get_repo, get_tenant_id
from api.schemas.decision import DecisionRecordCreate, DecisionRecordRead
from core.decision import DecisionRecord
from use_cases.decision_records import create_decision_record_use_case

router = APIRouter(prefix="/api/v1/decision-records", tags=["decision-records"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[Any, Depends(get_repo)]


Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]
DecisionFilter = Annotated[str | None, Query()]
MadeByFilter = Annotated[str | None, Query()]


def _row_to_read(row) -> DecisionRecordRead:
    return DecisionRecordRead(
        id=row.id,
        created_at=row.created_at,
        made_by=row.made_by,
        decision=row.decision,
        confidence=row.confidence,
        rationale=row.rationale,
        notes=row.notes,
        hypothesis_ids=[h.id for h in (row.hypotheses or [])],
        action_ids=[a.id for a in (row.actions or [])],
        error_ids=[e.id for e in (row.errors or [])],
        potential_id=row.potential_id,
    )


@router.post("", response_model=DecisionRecordRead, status_code=status.HTTP_201_CREATED)
def create_decision_record(
    payload: DecisionRecordCreate, tenant_id: TenantId, repo: RepoDep
) -> DecisionRecordRead:
    try:
        record = DecisionRecord(**payload.model_dump(exclude_none=True))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    create_decision_record_use_case(repo, tenant_id, record)
    row = repo.get_decision_record(tenant_id, str(record.id))
    if row is None:
        raise HTTPException(status_code=404, detail="DecisionRecord not found")
    return _row_to_read(row)


@router.get("", response_model=list[DecisionRecordRead])
def list_decision_records(
    tenant_id: TenantId,
    repo: RepoDep,
    response: Response,
    limit: Limit = 50,
    offset: Offset = 0,
    decision: DecisionFilter = None,
    made_by: MadeByFilter = None,
) -> list[DecisionRecordRead]:
    total = repo.count_decision_records(tenant_id, decision=decision, made_by=made_by)
    response.headers["X-Total-Count"] = str(total)

    rows = repo.list_decision_records(
        tenant_id,
        limit=limit,
        offset=offset,
        decision=decision,
        made_by=made_by,
    )
    return [_row_to_read(r) for r in rows]


@router.get("/{record_id}", response_model=DecisionRecordRead)
def get_decision_record(record_id: str, tenant_id: TenantId, repo: RepoDep) -> DecisionRecordRead:
    row = repo.get_decision_record(tenant_id, record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="DecisionRecord not found")
    return _row_to_read(row)
