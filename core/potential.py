from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DataPotentialStatus(StrEnum):
    DRAFT = "draft"
    ESTIMATED = "estimated"
    STALE = "stale"  # needs refresh due to data/model drift


class DataPotential(BaseModel):
    """Estimation of reasonable upper-bound expectations from data (NOT a forecast).

    Canon:
      - no promises
      - uncertainty is explicit
      - assumptions are explicit
      - evidence is required for ESTIMATED (No Oracle Rule)
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: DataPotentialStatus = DataPotentialStatus.DRAFT

    metric_name: str = Field(min_length=2, max_length=64, description="E.g. accuracy, F1, CER")
    current: float = Field(ge=0.0, le=1.0, description="Current metric value (0..1).")

    # Main output: a bounded range (0..1) for the *reasonable upper bound* given data constraints.
    upper_bound_range: tuple[float, float] | None = Field(
        default=None,
        description="(low, high) for reasonable upper bound (0..1). Not a prediction.",
    )

    # Optional named scenarios (views) on top of ranges.
    scenarios: dict[str, tuple[float, float]] | None = Field(
        default=None,
        description='Optional named ranges, e.g. {"best_case": (0.82,0.86), "worst_case": (0.75,0.78)}.',
    )

    confidence: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Confidence in the estimate (0..1). About the estimate, not the metric.",
    )

    sample_size: int = Field(
        default=0, ge=0, description="How many evaluation samples back this estimate."
    )

    limiting_factors: list[str] = Field(
        default_factory=list,
        description="Why the data is likely the bottleneck (noise, ambiguity, drift, coverage gaps).",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Explicit conditions for this estimate to hold.",
    )

    evidence_error_ids: list[UUID] = Field(
        default_factory=list,
        description="Errors that motivated this estimate (legacy error-driven flow).",
    )
    evidence_run_ids: list[str] = Field(
        default_factory=list,
        description="Runs that motivated this estimate (analytics-driven flow).",
    )
    notes: str | None = Field(default=None, max_length=2_000)

    @field_validator("limiting_factors", "assumptions")
    @classmethod
    def _no_empty_items(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v]
        if any(s == "" for s in cleaned):
            raise ValueError("items must be non-empty strings")
        return cleaned

    @field_validator("evidence_run_ids")
    @classmethod
    def _no_empty_run_ids(cls, v: list[str]) -> list[str]:
        cleaned = [s.strip() for s in v]
        if any(s == "" for s in cleaned):
            raise ValueError("evidence_run_ids items must be non-empty strings")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("evidence_run_ids must not contain duplicates")
        return cleaned

    @staticmethod
    def _validate_range(r: tuple[float, float], *, current: float) -> None:
        lo, hi = r
        if not (0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0):
            raise ValueError("upper bound range values must be within 0..1")
        if lo > hi:
            raise ValueError("upper_bound_range must satisfy low <= high")
        if hi < current:
            raise ValueError("upper_bound_range high must be >= current")

    @model_validator(mode="after")
    def _invariants(self) -> DataPotential:
        if self.upper_bound_range is not None:
            self._validate_range(self.upper_bound_range, current=self.current)

        if self.scenarios is not None:
            for name, r in self.scenarios.items():
                if not isinstance(name, str) or name.strip() == "":
                    raise ValueError("scenario names must be non-empty strings")
                self._validate_range(r, current=self.current)

        if self.status == DataPotentialStatus.ESTIMATED:
            if self.upper_bound_range is None:
                raise ValueError("ESTIMATED potential must set upper_bound_range")
            if not self.limiting_factors:
                raise ValueError("ESTIMATED potential must include limiting_factors")
            if not self.assumptions:
                raise ValueError("ESTIMATED potential must include assumptions")
            if self.sample_size <= 0:
                raise ValueError("ESTIMATED potential must set sample_size > 0")
            if not self.evidence_error_ids and not self.evidence_run_ids:
                raise ValueError(
                    "ESTIMATED potential must reference evidence: "
                    "evidence_error_ids and/or evidence_run_ids"
                )

        return self
