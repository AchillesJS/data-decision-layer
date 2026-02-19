from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol


class HasId(Protocol):
    # NOTE:
    # Store layer uses SQLAlchemy typed declarative (Mapped[T]) without a mypy plugin.
    # Therefore ORM instance attributes are seen by mypy as Mapped[T], not T.
    # In the API layer we only need a "row-like" shape, so we keep attribute
    # value types as Any to remain compatible with ORM models.
    id: Any


class ErrorRowLike(Protocol):
    id: Any
    created_at: Any
    updated_at: Any
    status: Any
    y_true: Any
    y_pred: Any
    confidence: Any
    uncertainty: Any
    repeatability: Any
    example_ref: Any
    context: Any


class HypothesisRowLike(Protocol):
    id: Any
    created_at: Any
    updated_at: Any
    status: Any
    title: Any
    statement: Any
    arguments: Any
    alternatives: Any
    uncertainty: Any
    errors: Any
    scope: Any
    tags: Any


class ActionRowLike(Protocol):
    id: Any
    created_at: Any
    updated_at: Any
    status: Any
    hypothesis_id: Any
    name: Any
    description: Any
    risk_if_false: Any
    cost: Any
    expected_artifacts: Any
    completed_at: Any
    cancel_reason: Any


class DecisionRecordRowLike(Protocol):
    id: Any
    created_at: Any
    made_by: Any
    decision: Any
    confidence: Any
    rationale: Any
    notes: Any
    hypotheses: Any
    actions: Any
    errors: Any
    potential_id: Any


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
    ) -> Sequence[ErrorRowLike]: ...

    def count_errors(
        self,
        tenant_id: str,
        *,
        status: str | None,
        y_true: str | None,
        y_pred: str | None,
    ) -> int: ...

    def get_error(self, tenant_id: str, error_id: str) -> ErrorRowLike | None: ...

    # hypotheses
    def list_hypotheses(
        self,
        tenant_id: str,
        *,
        limit: int,
        offset: int,
        status: str | None,
        evidence_error_id: str | None,
    ) -> Sequence[HypothesisRowLike]: ...

    def count_hypotheses(
        self,
        tenant_id: str,
        *,
        status: str | None,
        evidence_error_id: str | None,
    ) -> int: ...

    def get_hypothesis(
        self, tenant_id: str, hypothesis_id: str
    ) -> HypothesisRowLike | None: ...

    # actions
    def list_actions(
        self,
        tenant_id: str,
        *,
        limit: int,
        offset: int,
        status: str | None,
        hypothesis_id: str | None,
    ) -> Sequence[ActionRowLike]: ...

    def count_actions(
        self,
        tenant_id: str,
        *,
        status: str | None,
        hypothesis_id: str | None,
    ) -> int: ...

    def get_action(self, tenant_id: str, action_id: str) -> ActionRowLike | None: ...

    # decisions
    def list_decision_records(
        self,
        tenant_id: str,
        *,
        limit: int,
        offset: int,
        decision: str | None,
        made_by: str | None,
    ) -> Sequence[DecisionRecordRowLike]: ...

    def count_decision_records(
        self,
        tenant_id: str,
        *,
        decision: str | None,
        made_by: str | None,
    ) -> int: ...

    def get_decision_record(
        self, tenant_id: str, record_id: str
    ) -> DecisionRecordRowLike | None: ...
