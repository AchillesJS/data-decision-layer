from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException

from api.protocols import RepoProtocol
from store.repository import Repository

_REPO: RepoProtocol | None = None


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
