from __future__ import annotations

from typing import Annotated, Any, Protocol, runtime_checkable

from fastapi import Header, HTTPException

from store.repository import Repository


@runtime_checkable
class RepoProtocol(Protocol):
    # errors
    def list_errors(
        self,
        tenant_id: str,
        *,
        limit: int,
        offset: int,
        status: str | None,
        y_true: str | None,
        y_pred: str | None,
    ) -> list[Any]: ...

    def count_errors(
        self,
        tenant_id: str,
        *,
        status: str | None,
        y_true: str | None,
        y_pred: str | None,
    ) -> int: ...

    def get_error(self, tenant_id: str, error_id: str) -> Any | None: ...

    # hypotheses
    def list_hypotheses(
        self,
        tenant_id: str,
        *,
        limit: int,
        offset: int,
        status: str | None,
        evidence_error_id: str | None,
    ) -> list[Any]: ...

    def count_hypotheses(
        self,
        tenant_id: str,
        *,
        status: str | None,
        evidence_error_id: str | None,
    ) -> int: ...

    def get_hypothesis(self, tenant_id: str, hypothesis_id: str) -> Any | None: ...

    # actions
    def list_actions(
        self,
        tenant_id: str,
        *,
        limit: int,
        offset: int,
        status: str | None,
        hypothesis_id: str | None,
    ) -> list[Any]: ...

    def count_actions(
        self,
        tenant_id: str,
        *,
        status: str | None,
        hypothesis_id: str | None,
    ) -> int: ...

    def get_action(self, tenant_id: str, action_id: str) -> Any | None: ...

    # decisions
    def list_decision_records(
        self,
        tenant_id: str,
        *,
        limit: int,
        offset: int,
        decision: str | None,
        made_by: str | None,
    ) -> list[Any]: ...

    def count_decision_records(
        self,
        tenant_id: str,
        *,
        decision: str | None,
        made_by: str | None,
    ) -> int: ...

    def get_decision_record(self, tenant_id: str, record_id: str) -> Any | None: ...


_REPO: Repository | None = None


def get_repo() -> RepoProtocol:
    """Repository dependency.

    Uses Repository.sqlite() which resolves DB URL from DDW_DB_URL.
    Lazily initialized to keep import side-effects minimal.
    """

    global _REPO
    if _REPO is None:
        _REPO = Repository.sqlite()
    return _REPO


def get_tenant_id(x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None) -> str:
    """Tenant dependency.

    Tenant id is REQUIRED for all endpoints except /health.
    """

    if x_tenant_id is None or not x_tenant_id.strip():
        # Missing required header is a validation error.
        raise HTTPException(status_code=422, detail="Missing X-Tenant-Id header")
    return x_tenant_id.strip()
