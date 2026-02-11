from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ActionStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CostEstimate(BaseModel):
    """Explicit cost; not an uplift promise.

    Use any unit you want (hours, RMB, USD).
    """

    model_config = ConfigDict(extra="forbid")

    time_hours: float | None = Field(default=None, ge=0.0)
    money: float | None = Field(default=None, ge=0.0)
    note: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def _at_least_one_dimension(self) -> CostEstimate:
        if self.time_hours is None and self.money is None:
            raise ValueError("CostEstimate must set at least one of: time_hours, money")
        return self


class Action(BaseModel):
    """A concrete data action.

    Canon rules enforced:
    - Action must be linked to a hypothesis.
    - Action must have explicit risk and cost.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    status: ActionStatus = ActionStatus.PROPOSED

    hypothesis_id: UUID | None = Field(default=None, description="Hypothesis this action is intended to test. May be None only in DRAFT.")
    name: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10, max_length=2_000)

    risk_if_false: RiskLevel = Field(description="Risk if the hypothesis is false but we execute this action.")
    cost: CostEstimate

    expected_artifacts: list[str] = Field(
        default_factory=list,
        description="What this action should produce (labels, dataset slice, audit notes, etc.).",
    )

    completed_at: datetime | None = None
    cancel_reason: str | None = Field(default=None, max_length=240)

    @field_validator("expected_artifacts")
    @classmethod
    def _no_empty_artifacts(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v]
        if any(s == "" for s in cleaned):
            raise ValueError("expected_artifacts items must be non-empty strings")
        return cleaned

    @model_validator(mode="after")
    def _invariants(self) -> Action:
        # Exploratory workflow: allow missing hypothesis_id only in DRAFT.
        if self.status != ActionStatus.DRAFT and self.hypothesis_id is None:
            raise ValueError("Non-DRAFT actions must set hypothesis_id")

        if self.status == ActionStatus.DONE:
            if self.completed_at is None:
                raise ValueError("DONE actions must set completed_at")
        else:
            if self.completed_at is not None:
                raise ValueError("completed_at is only allowed when status=DONE")

        if self.status == ActionStatus.CANCELLED:
            if not self.cancel_reason:
                raise ValueError("CANCELLED actions must include cancel_reason")
        else:
            if self.cancel_reason is not None:
                raise ValueError("cancel_reason is only allowed when status=CANCELLED")

        return self
