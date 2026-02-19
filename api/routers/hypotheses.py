from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from api.deps import get_repo, get_tenant_id
from api.schemas.hypothesis import HypothesisCreate, HypothesisRead
from core.hypothesis import Hypothesis
from use_cases.hypotheses import create_hypothesis_use_case

router = APIRouter(prefix="/api/v1/hypotheses", tags=["hypotheses"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[Any, Depends(get_repo)]


def _row_to_read(row) -> HypothesisRead:
    return HypothesisRead(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        status=row.status,
        title=row.title,
        statement=row.statement,
        arguments=list(row.arguments or []),
        alternatives=list(row.alternatives or []),
        uncertainty=row.uncertainty,
        evidence_error_ids=[e.id for e in (row.errors or [])],
        scope=row.scope,
        tags=list(row.tags or []),
    )


@router.post("", response_model=HypothesisRead, status_code=status.HTTP_201_CREATED)
def create_hypothesis(payload: HypothesisCreate, tenant_id: TenantId, repo: RepoDep) -> HypothesisRead:
    try:
        hyp = Hypothesis(**payload.model_dump(exclude_none=True))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    hid = create_hypothesis_use_case(repo, tenant_id, hyp, error_ids=payload.evidence_error_ids)
    row = repo.get_hypothesis(tenant_id, hid)
    if row is None:
        raise HTTPException(status_code=404, detail="Hypothesis not found")
    return _row_to_read(row)


@router.get("/{hypothesis_id}", response_model=HypothesisRead)
def get_hypothesis(hypothesis_id: str, tenant_id: TenantId, repo: RepoDep) -> HypothesisRead:
    row = repo.get_hypothesis(tenant_id, hypothesis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Hypothesis not found")
    return _row_to_read(row)
