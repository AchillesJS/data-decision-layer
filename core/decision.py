from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DecisionType(StrEnum):
    PROCEED = "proceed"  # commit to one or more actions
    DEFER = "defer"  # keep in backlog; not enough info
    REJECT = "reject"  # do not do actions (now)


class DecisionRecord(BaseModel):
    """A single immutable record of a decision made by a human.

    This is *not* the decision itself; it's the history and justification.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    made_by: str = Field(min_length=1, max_length=120)
    decision: DecisionType
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence in this decision, not a promise of metric change (0..1).",
    )
    rationale: str = Field(min_length=10, max_length=4_000)

    # links
    hypothesis_ids: list[UUID] = Field(default_factory=list)
    action_ids: list[UUID] = Field(default_factory=list)
    error_ids: list[UUID] = Field(default_factory=list)
    potential_id: UUID | None = None

    notes: str | None = Field(default=None, max_length=4_000)

    @field_validator("hypothesis_ids", "action_ids", "error_ids")
    @classmethod
    def _no_duplicates(cls, v: list[UUID]) -> list[UUID]:
        if len(set(v)) != len(v):
            raise ValueError("ids lists must not contain duplicates")
        return v

    @model_validator(mode="after")
    def _invariants(self) -> DecisionRecord:
        if not (self.hypothesis_ids or self.action_ids or self.error_ids or self.potential_id):
            raise ValueError(
                "DecisionRecord must reference at least one of: hypothesis_ids, action_ids, error_ids, potential_id"
            )

        if self.decision == DecisionType.PROCEED:
            if not self.action_ids:
                raise ValueError("PROCEED decisions must reference at least one action_id")
        elif self.decision == DecisionType.REJECT:
            if self.action_ids:
                raise ValueError("REJECT decisions must not reference action_ids")

        return self
