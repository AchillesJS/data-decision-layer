from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DataPotentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    metric_name: str
    current: float = Field(ge=0.0)

    upper_bound_range: list[float] | None = None
    scenarios: dict[str, list[float]] = Field(default_factory=dict)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sample_size: int = Field(default=0, ge=0)

    limiting_factors: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evidence_error_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class DataPotentialRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: datetime
    updated_at: datetime
    status: str

    metric_name: str
    current: float
    upper_bound_range: list[float] | None
    scenarios: dict[str, list[float]]
    confidence: float
    sample_size: int
    limiting_factors: list[str]
    assumptions: list[str]
    evidence_error_ids: list[str]
    notes: str | None
