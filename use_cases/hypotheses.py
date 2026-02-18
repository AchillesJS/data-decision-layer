from __future__ import annotations

from core.hypothesis import Hypothesis
from store.repository import Repository


class UseCaseIntegrityError(ValueError):
    """Raised when referential integrity constraints are violated."""


def create_hypothesis_use_case(
    repo: Repository,
    tenant_id: str,
    hypothesis: Hypothesis,
    error_ids: list[str] | None = None,
) -> str:
    """Create Hypothesis with strict linking to errors (H1) inside a tenant.

    H1:
      - if error_ids provided and non-empty, all must exist *inside tenant*;
        otherwise raise UseCaseIntegrityError and do not persist.

    Multi-tenant rules:
      - all checks are tenant-scoped (R3 anti-cross-tenant by construction).

    All checks + write happen in ONE transaction.
    """

    ids: list[str] = list(error_ids) if error_ids else []

    with repo.session() as s:  
        if ids and not repo.errors_exist_in_session(s, tenant_id, ids):
            raise UseCaseIntegrityError("Hypothesis references missing error_id")

        repo.create_hypothesis_in_session(s, tenant_id, hypothesis, link_error_ids=ids or None)

    return str(hypothesis.id)
