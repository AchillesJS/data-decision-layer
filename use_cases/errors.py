from __future__ import annotations

from core.error import Error
from store.models import ErrorRow
from store.repository import Repository


def create_error_use_case(repo: Repository, tenant_id: str, error: Error) -> ErrorRow:
    """Create an Error in a single transaction.

    No integrity checks are required for MVP.
    """

    with repo.session() as s:
        row = repo.create_error_in_session(s, tenant_id, error)
    return row
