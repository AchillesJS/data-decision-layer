from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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
