from __future__ import annotations

from sqlalchemy.orm import Session

from store.repository import Repository
from use_cases.transitions import ensure_transition

_SESSION_TYPE = Session


class NotFoundError(ValueError):
    pass


def _archive_entity_use_case(
    repo: Repository,
    *,
    entity_type: str,
    entity_id: str,
) -> None:
    """Shared archive orchestration.

    Steps (ONE txn):
      1) read current status
      2) ensure_transition(entity_type, from, archived)
      3) archive via store
    """

    with repo.session() as s:  # type: Session
        current = repo.get_status_in_session(s, entity_type, entity_id)
        if current is None:
            raise NotFoundError(f"{entity_type} not found")

        ensure_transition(entity_type, current, "archived")

        if entity_type == "error":
            repo.archive_error_in_session(s, entity_id)
        elif entity_type == "hypothesis":
            repo.archive_hypothesis_in_session(s, entity_id)
        elif entity_type == "action":
            repo.archive_action_in_session(s, entity_id)
        elif entity_type == "data_potential":
            repo.archive_data_potential_in_session(s, entity_id)
        else:
            raise ValueError(f"Unknown entity_type: {entity_type!r}")


def archive_error_use_case(repo: Repository, error_id: str) -> None:
    _archive_entity_use_case(repo, entity_type="error", entity_id=error_id)


def archive_hypothesis_use_case(repo: Repository, hypothesis_id: str) -> None:
    _archive_entity_use_case(repo, entity_type="hypothesis", entity_id=hypothesis_id)


def archive_action_use_case(repo: Repository, action_id: str) -> None:
    _archive_entity_use_case(repo, entity_type="action", entity_id=action_id)


def archive_data_potential_use_case(repo: Repository, potential_id: str) -> None:
    _archive_entity_use_case(repo, entity_type="data_potential", entity_id=potential_id)
