from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from core.action import Action, ActionStatus
from core.hypothesis import Hypothesis, HypothesisStatus
from store.repository import Repository
from use_cases.actions import UseCaseValidationError


class ForbiddenTransitionError(ValueError):
    """Raised when a status transition is not allowed by docs/state_machine.md."""


_Transition = tuple[str, str]


# IMPORTANT: keep this in sync with docs/state_machine.md
ALLOWED_TRANSITIONS: Mapping[str, set[_Transition]] = {
    "error": {
        ("observed", "triaged"),
        ("observed", "archived"),
        ("triaged", "archived"),
    },
    "hypothesis": {
        ("draft", "active"),
        ("active", "testing"),
        ("testing", "supported"),
        ("testing", "refuted"),
        # archive supports * -> archived
        ("draft", "archived"),
        ("active", "archived"),
        ("testing", "archived"),
        ("supported", "archived"),
        ("refuted", "archived"),
    },
    "action": {
        ("draft", "proposed"),
        ("proposed", "approved"),
        ("approved", "in_progress"),
        ("in_progress", "done"),
        ("draft", "cancelled"),
        ("proposed", "cancelled"),
        ("approved", "cancelled"),
        ("in_progress", "cancelled"),
        # archive supports * -> archived
        ("draft", "archived"),
        ("proposed", "archived"),
        ("approved", "archived"),
        ("in_progress", "archived"),
        ("done", "archived"),
        ("cancelled", "archived"),
    },
    "data_potential": {
        ("draft", "estimated"),
        ("estimated", "stale"),
        # archive supports * -> archived
        ("draft", "archived"),
        ("estimated", "archived"),
        ("stale", "archived"),
    },
    # Backward-compatible alias (do not use in new code)
    "potential": {
        ("draft", "estimated"),
        ("estimated", "stale"),
        ("draft", "archived"),
        ("estimated", "archived"),
        ("stale", "archived"),
    },
}


def ensure_transition(entity_type: str, from_status: Any, to_status: Any) -> None:
    """Validate transition.

    Accepts either Enum-like objects with `.value` or raw strings.
    Raises ForbiddenTransitionError if not allowed.
    """
    et = entity_type.strip().lower()
    if et not in ALLOWED_TRANSITIONS:
        raise ValueError(f"Unknown entity_type: {entity_type!r}")

    f = getattr(from_status, "value", from_status)
    t = getattr(to_status, "value", to_status)
    key = (str(f), str(t))

    if key not in ALLOWED_TRANSITIONS[et]:
        raise ForbiddenTransitionError(f"Forbidden transition for {et}: {key[0]} -> {key[1]}")


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def transition_action_use_case(
    repo: Repository,
    tenant_id: str,
    action_id: str,
    to_status: ActionStatus,
) -> None:
    """Transition an Action status inside a tenant (ONE txn).

    Side effects beyond status change:
      - DONE: completed_at is auto-set to now.
      - non-DONE (from any prior state): completed_at is cleared.
      - CANCELLED is REJECTED here: it requires cancel_reason and must use
        a dedicated cancel endpoint (TransitionRequest carries no reason).
    """

    # Local import to avoid a module import cycle:
    # use_cases.archive imports ensure_transition from this module.
    from use_cases.archive import NotFoundError

    if to_status == ActionStatus.CANCELLED:
        raise UseCaseValidationError(
            "Cancelling an Action requires cancel_reason; use a dedicated cancel endpoint."
        )

    with repo.session() as s:
        row = repo.get_action_in_session(s, tenant_id, action_id)
        if row is None:
            raise NotFoundError("Action not found")

        ensure_transition("action", row.status, to_status.value)

        now = _utcnow_naive()
        new_completed_at: datetime | None = (
            now if to_status == ActionStatus.DONE else None
        )

        payload: dict[str, Any] = {
            "id": row.id,
            "created_at": row.created_at,
            "updated_at": now,
            "status": to_status,
            "hypothesis_id": row.hypothesis_id,
            "name": row.name,
            "description": row.description,
            "risk_if_false": row.risk_if_false,
            "cost": row.cost,
            "expected_artifacts": list(row.expected_artifacts or []),
            "completed_at": new_completed_at,
            "cancel_reason": row.cancel_reason,
        }

        try:
            Action.model_validate(payload)
        except ValidationError as exc:
            raise UseCaseValidationError(
                "Action transition violates invariants", errors=exc.errors()
            ) from exc

        row.status = to_status.value
        row.updated_at = now
        row.completed_at = new_completed_at


def transition_hypothesis_use_case(
    repo: Repository,
    tenant_id: str,
    hypothesis_id: str,
    to_status: HypothesisStatus,
) -> None:
    """Transition a Hypothesis status inside a tenant (ONE txn)."""

    # Local import to avoid a module import cycle:
    # use_cases.archive imports ensure_transition from this module.
    from use_cases.archive import NotFoundError

    with repo.session() as s:
        row = repo.get_hypothesis_in_session(s, tenant_id, hypothesis_id)
        if row is None:
            raise NotFoundError("Hypothesis not found")

        ensure_transition("hypothesis", row.status, to_status.value)

        payload: dict[str, Any] = {
            "id": row.id,
            "created_at": row.created_at,
            "updated_at": _utcnow_naive(),
            "status": to_status,
            "title": row.title,
            "statement": row.statement,
            "arguments": list(row.arguments or []),
            "alternatives": list(row.alternatives or []),
            "uncertainty": row.uncertainty,
            "evidence_error_ids": [e.id for e in (row.errors or [])],
            "scope": row.scope,
            "tags": list(row.tags or []),
        }

        try:
            Hypothesis.model_validate(payload)
        except ValidationError as exc:
            raise UseCaseValidationError(
                "Hypothesis transition violates invariants", errors=exc.errors()
            ) from exc

        row.status = to_status.value
        row.updated_at = _utcnow_naive()
