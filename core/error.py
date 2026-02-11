from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ErrorStatus(StrEnum):
    """Lifecycle of a single error example inside the workspace."""

    OBSERVED = "observed"   # collected, not triaged
    TRIAGED = "triaged"     # reviewed, described, grouped
    ARCHIVED = "archived"   # kept for history, not actively worked


class Error(BaseModel):
    """One concrete model error example (object of thinking).

    Notes:
    - This is NOT a metric; it's an example + context.
    - No DB assumptions here.
    - No causal claims here.
    """

    model_config = ConfigDict(extra="forbid")

    # identity / time
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: ErrorStatus = ErrorStatus.OBSERVED

    # core mismatch
    y_true: str = Field(min_length=1)
    y_pred: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)

    # uncertainty & repeatability
    uncertainty: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Uncertainty about interpreting this error (0..1).",
    )
    repeatability: int = Field(
        default=1,
        ge=1,
        description="How many times we saw the same pattern (>=1).",
    )

    # optional context / cost / references
    example_ref: str | None = Field(
        default=None, description="Path/URL/hash to the underlying example."
    )
    context: dict[str, Any] | None = Field(
        default=None, description="Context metadata (device, country, source, etc.)."
    )

    @field_validator("example_ref")
    @classmethod
    def _empty_string_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return None if v == "" else v

    @field_validator("context")
    @classmethod
    def _validate_context_keys(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return None
        for k in v.keys():
            if not isinstance(k, str) or k.strip() == "":
                raise ValueError("context keys must be non-empty strings")
        return v

    @model_validator(mode="after")
    def _invariants(self) -> Error:
        if self.y_true == self.y_pred:
            raise ValueError("Error requires mismatch: y_true must differ from y_pred")
        return self
