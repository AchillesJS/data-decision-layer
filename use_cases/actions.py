from __future__ import annotations

from typing import Any

from core.action import Action, ActionStatus
from store.repository import Repository


class UseCaseValidationError(ValueError):
    def __init__(self, message: str, *, errors: list[Any] | None = None) -> None:
        super().__init__(message)
        self.errors = errors



def create_action_use_case(repo: Repository, tenant_id: str, action: Action) -> None:
    """Persist an Action inside a tenant.

    Integrity rules belong here, not in store:
      - if status != DRAFT, hypothesis_id must be provided.

    Multi-tenant rules:
      - the write is tenant-scoped.
    """

    if action.status != ActionStatus.DRAFT and action.hypothesis_id is None:
        raise UseCaseValidationError("Non-DRAFT actions must set hypothesis_id")

    with repo.session() as s:  
        # (R1)+(R3) referenced hypothesis_id must exist inside tenant.
        if action.hypothesis_id is not None:
            if not repo.hypotheses_exist_in_session(s, tenant_id, [str(action.hypothesis_id)]):
                raise UseCaseValidationError("Action references missing hypothesis_id")

        repo.create_action_in_session(s, tenant_id, action)
