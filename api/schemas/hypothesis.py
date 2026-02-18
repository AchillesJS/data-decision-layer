from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ErrorScopeDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filters: dict[str, str] | None = None
    y_true: str | None = None
    y_pred: str | None = None
    confidence_min: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence_max: float | None = Field(default=None, ge=0.0, le=1.0)
    min_count: int = Field(default=1, ge=1)


class HypothesisCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    statement: str | None = None
    status: str | None = None
    arguments: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    uncertainty: float = Field(default=0.6, ge=0.0, le=1.0)
    evidence_error_ids: list[str] = Field(default_factory=list)
    scope: ErrorScopeDTO | None = None
    tags: list[str] = Field(default_factory=list)


class HypothesisRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: datetime
    updated_at: datetime
    status: str

    title: str
    statement: str | None
    arguments: list[str]
    alternatives: list[str]
    uncertainty: float
    evidence_error_ids: list[str]
    scope: dict | None
    tags: list[str]
