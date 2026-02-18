from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DecisionRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    made_by: str
    decision: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    hypothesis_ids: list[str] = Field(default_factory=list)
    action_ids: list[str] = Field(default_factory=list)
    error_ids: list[str] = Field(default_factory=list)
    potential_id: str | None = None
    notes: str | None = None


class DecisionRecordRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: datetime
    made_by: str
    decision: str
    confidence: float
    rationale: str
    notes: str | None
    hypothesis_ids: list[str]
    action_ids: list[str]
    error_ids: list[str]
    potential_id: str | None
