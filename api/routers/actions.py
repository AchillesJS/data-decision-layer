from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError

from api.deps import RepoProtocol, get_repo, get_tenant_id
from api.schemas.action import ActionCreate, ActionRead
from core.action import Action
from use_cases.actions import create_action_use_case
from use_cases.archive import archive_action_use_case

router = APIRouter(prefix="/api/v1/actions", tags=["actions"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[RepoProtocol, Depends(get_repo)]


Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]
StatusFilter = Annotated[str | None, Query()]
HypothesisIdFilter = Annotated[str | None, Query()]


def _row_to_read(row: Any) -> ActionRead:
    return ActionRead(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        status=row.status,
        hypothesis_id=row.hypothesis_id,
        name=row.name,
        description=row.description,
        risk_if_false=row.risk_if_false,
        cost=row.cost,
        expected_artifacts=list(row.expected_artifacts or []),
        completed_at=row.completed_at,
        cancel_reason=row.cancel_reason,
    )


@router.post("", response_model=ActionRead, status_code=status.HTTP_201_CREATED)
def create_action(payload: ActionCreate, tenant_id: TenantId, repo: RepoDep) -> ActionRead:
    try:
        act = Action(**payload.model_dump(exclude_none=True))
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    create_action_use_case(cast(Any, repo), tenant_id, act)

    row = repo.get_action(tenant_id, str(act.id))
    if row is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return _row_to_read(row)


@router.get("", response_model=list[ActionRead])
def list_actions(
    tenant_id: TenantId,
    repo: RepoDep,
    response: Response,
    limit: Limit = 50,
    offset: Offset = 0,
    status: StatusFilter = None,
    hypothesis_id: HypothesisIdFilter = None,
) -> list[ActionRead]:
    total = repo.count_actions(tenant_id, status=status, hypothesis_id=hypothesis_id)
    response.headers["X-Total-Count"] = str(total)

    rows = repo.list_actions(
        tenant_id,
        limit=limit,
        offset=offset,
        status=status,
        hypothesis_id=hypothesis_id,
    )
    return [_row_to_read(r) for r in rows]


@router.get("/{action_id}", response_model=ActionRead)
def get_action(action_id: str, tenant_id: TenantId, repo: RepoDep) -> ActionRead:
    row = repo.get_action(tenant_id, action_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return _row_to_read(row)


@router.post("/{action_id}/archive", response_model=ActionRead)
def archive_action(action_id: str, tenant_id: TenantId, repo: RepoDep) -> ActionRead:
    archive_action_use_case(cast(Any, repo), tenant_id, action_id)
    row = repo.get_action(tenant_id, action_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return _row_to_read(row)
