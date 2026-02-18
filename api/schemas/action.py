from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CostEstimateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_hours: float | None = Field(default=None, ge=0.0)
    money: float | None = Field(default=None, ge=0.0)
    note: str | None = Field(default=None, max_length=240)


class ActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    hypothesis_id: str | None = None
    name: str
    description: str
    risk_if_false: str
    cost: CostEstimateDTO
    expected_artifacts: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
    cancel_reason: str | None = None


class ActionRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: datetime
    updated_at: datetime
    status: str

    hypothesis_id: str | None
    name: str
    description: str
    risk_if_false: str
    cost: dict
    expected_artifacts: list[str]
    completed_at: datetime | None
    cancel_reason: str | None
