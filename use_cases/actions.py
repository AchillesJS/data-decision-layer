from __future__ import annotations

from core.action import Action, ActionStatus
from store.repository import Repository


class UseCaseValidationError(ValueError):
    pass


def create_action_use_case(repo: Repository, action: Action) -> None:
    """Persist an Action.

    Integrity rules belong here, not in store:
      - if status != DRAFT, hypothesis_id must be provided.
    """
    if action.status != ActionStatus.DRAFT and action.hypothesis_id is None:
        raise UseCaseValidationError("Non-DRAFT actions must set hypothesis_id")

    with repo.session() as s:
        repo.create_action_in_session(s, action)
