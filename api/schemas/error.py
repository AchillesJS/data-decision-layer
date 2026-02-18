from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ErrorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    y_true: str
    y_pred: str
    confidence: float = Field(ge=0.0, le=1.0)
    uncertainty: float | None = Field(default=None, ge=0.0, le=1.0)
    repeatability: int | None = Field(default=None, ge=1)
    example_ref: str | None = None
    context: dict | None = None


class ErrorRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: datetime
    updated_at: datetime
    status: str

    y_true: str
    y_pred: str
    confidence: float
    uncertainty: float
    repeatability: int
    example_ref: str | None
    context: dict
