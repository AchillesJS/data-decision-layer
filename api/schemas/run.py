from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RunCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: str
    dataset_version: str | None = None
    dataset_size: float = Field(gt=0)
    model_tag: str = Field(min_length=1)
    seed: int | None = None

    budget_kind: str
    budget_value: float = Field(gt=0)

    metric_name: str = Field(min_length=1)
    split: str | None = None
    metric_final: float = Field(ge=0, le=1)

    config_hash: str | None = None
    git_commit: str | None = None


class RunRead(RunCreate):
    id: str
    created_at: datetime
    updated_at: datetime
