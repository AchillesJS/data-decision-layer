from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, status

from api.deps import get_repo, get_tenant_id
from api.schemas.jobs import RunnerRead, RunnerRegisterRequest, RunnerRegisterResponse
from use_cases.runners import heartbeat_runner, list_runners, register_runner

router = APIRouter(prefix="/api/v1/runners", tags=["runners"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[Any, Depends(get_repo)]
RunnerToken = Annotated[str, Header(alias="X-Runner-Token")]


def _runner_to_read(row: Any) -> RunnerRead:
    return RunnerRead(
        id=str(row.id),
        name=row.name,
        tags=list(row.tags_json or []),
        status=str(row.status),
        last_seen_at=row.last_seen_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/register", response_model=RunnerRegisterResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RunnerRegisterRequest, tenant_id: TenantId, repo: RepoDep) -> RunnerRegisterResponse:
    result = register_runner(repo, tenant_id, name=payload.name, tags=payload.tags)
    return RunnerRegisterResponse(
        runner_id=result.runner_id,
        runner_token_plain_once=result.runner_token_plain_once,
    )


@router.post("/{runner_id}/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def heartbeat(runner_id: str, tenant_id: TenantId, repo: RepoDep, x_runner_token: RunnerToken) -> None:
    heartbeat_runner(repo, tenant_id, runner_id, x_runner_token)


@router.get("", response_model=list[RunnerRead])
def list_all(tenant_id: TenantId, repo: RepoDep) -> list[RunnerRead]:
    return [_runner_to_read(row) for row in list_runners(repo, tenant_id)]
