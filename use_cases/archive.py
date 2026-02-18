from __future__ import annotations

from store.repository import Repository
from use_cases.transitions import ensure_transition


class NotFoundError(ValueError):
    pass


def _archive_entity_use_case(
    repo: Repository,
    *,
    tenant_id: str,
    entity_type: str,
    entity_id: str,
) -> None:
    """Shared archive orchestration inside a tenant.

    Steps (ONE txn):
      1) read current status (tenant-scoped)
      2) ensure_transition(entity_type, from, archived)
      3) archive via store (tenant-scoped)
    """

    with repo.session() as s:  
        current = repo.get_status_in_session(s, tenant_id, entity_type, entity_id)
        if current is None:
            raise NotFoundError(f"{entity_type} not found")

        ensure_transition(entity_type, current, "archived")

        if entity_type == "error":
            repo.archive_error_in_session(s, tenant_id, entity_id)
        elif entity_type == "hypothesis":
            repo.archive_hypothesis_in_session(s, tenant_id, entity_id)
        elif entity_type == "action":
            repo.archive_action_in_session(s, tenant_id, entity_id)
        elif entity_type == "data_potential":
            repo.archive_data_potential_in_session(s, tenant_id, entity_id)
        else:
            raise ValueError(f"Unknown entity_type: {entity_type!r}")


def archive_error_use_case(repo: Repository, tenant_id: str, error_id: str) -> None:
    _archive_entity_use_case(repo, tenant_id=tenant_id, entity_type="error", entity_id=error_id)


def archive_hypothesis_use_case(repo: Repository, tenant_id: str, hypothesis_id: str) -> None:
    _archive_entity_use_case(
        repo, tenant_id=tenant_id, entity_type="hypothesis", entity_id=hypothesis_id
    )


def archive_action_use_case(repo: Repository, tenant_id: str, action_id: str) -> None:
    _archive_entity_use_case(repo, tenant_id=tenant_id, entity_type="action", entity_id=action_id)


def archive_data_potential_use_case(repo: Repository, tenant_id: str, potential_id: str) -> None:
    _archive_entity_use_case(
        repo, tenant_id=tenant_id, entity_type="data_potential", entity_id=potential_id
    )
