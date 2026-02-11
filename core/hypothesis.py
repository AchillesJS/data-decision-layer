from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HypothesisStatus(StrEnum):
    """A hypothesis is always a hypothesis (never a conclusion)."""

    DRAFT = "draft"
    ACTIVE = "active"
    TESTING = "testing"
    SUPPORTED = "supported"  # supported by evidence, not "proven"
    REFUTED = "refuted"
    ARCHIVED = "archived"


class ErrorScope(BaseModel):
    """A description of an error *set* (not a computed cluster).

    MVP intent:
    - Let a hypothesis refer to "the class of errors we mean" without building a clustering system.
    - This can later be materialized into an ErrorGroup if/when needed.
    """

    model_config = ConfigDict(extra="forbid")

    # Simple metadata filters (device=iphone, country=CN, source=..., etc.)
    filters: dict[str, Any] = Field(default_factory=dict)

    # Optional pattern constraints
    y_true: str | None = None
    y_pred: str | None = None
    confidence_min: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_max: float | None = Field(default=None, ge=0.0, le=1.0)

    min_count: int | None = Field(default=None, ge=1, description="Minimum occurrences for this scope to matter.")

    @model_validator(mode="after")
    def _scope_invariants(self) -> ErrorScope:
        if self.confidence_min is not None and self.confidence_max is not None:
            if self.confidence_min > self.confidence_max:
                raise ValueError("confidence_min must be <= confidence_max")
        for k in self.filters.keys():
            if not isinstance(k, str) or k.strip() == "":
                raise ValueError("filters keys must be non-empty strings")
        return self


class Hypothesis(BaseModel):
    """A testable statement about why errors happen.

    Canon:
    - not a conclusion
    - explicit uncertainty
    - linked to evidence (examples and/or scope)
    - linked to actions (that test it)
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: HypothesisStatus = HypothesisStatus.DRAFT

    title: str = Field(min_length=3, max_length=140)
    statement: str | None = Field(
        default=None,
        max_length=4_000,
        description="Core hypothesis statement. In DRAFT it may be empty; otherwise required.",
    )

    arguments: list[str] = Field(default_factory=list, description="Supporting arguments (non-empty strings).")
    alternatives: list[str] = Field(default_factory=list, description="Alternative hypotheses (non-empty strings).")
    uncertainty: float = Field(default=0.6, ge=0.0, le=1.0)

    evidence_error_ids: list[UUID] = Field(default_factory=list, description="Concrete error examples as evidence.")
    scope: ErrorScope | None = Field(default=None, description="Description of the error set this hypothesis targets.")
    tags: list[str] = Field(default_factory=list)

    @field_validator("arguments", "alternatives", "tags")
    @classmethod
    def _no_empty_strings_in_lists(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v]
        if any(s == "" for s in cleaned):
            raise ValueError("list items must be non-empty strings")
        return cleaned

    @field_validator("statement")
    @classmethod
    def _normalize_statement(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return None if v == "" else v

    @model_validator(mode="after")
    def _invariants(self) -> Hypothesis:
        # DRAFT may be incomplete; that's useful for workflow.
        if self.status != HypothesisStatus.DRAFT:
            if self.statement is None or len(self.statement) < 10:
                raise ValueError("Non-DRAFT hypothesis must set statement (min length 10)")
            # Need at least some grounding: argument OR evidence OR scope.
            if not self.arguments and not self.evidence_error_ids and self.scope is None:
                raise ValueError("Non-DRAFT hypothesis must have arguments, evidence_error_ids, or scope")

        # If marked as supported/refuted, require grounding (evidence or scope).
        if self.status in {HypothesisStatus.SUPPORTED, HypothesisStatus.REFUTED}:
            if not self.evidence_error_ids and self.scope is None:
                raise ValueError("SUPPORTED/REFUTED hypothesis must have evidence_error_ids or scope")

        return self
