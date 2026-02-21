from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunPoint(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    run_id: str
    x_kind: Literal["dataset_size", "budget"]
    x_value: float
    y_value: float
    seed: int | None = None
    model_tag: str
    dataset_version: str | None = None
    metric_name: str
    split: str | None = None
    created_at: datetime | None = None


class FitCoverage(BaseModel):
    n_points: int
    n_unique_x: int
    x_min: float
    x_max: float


class FitSanity(BaseModel):
    monotonic_expected: bool
    violations: list[str] = Field(default_factory=list)


class FitReport(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_family: Literal["log", "power", "none"]
    fit_quality: Literal["ok", "weak", "bad", "insufficient_data"]
    mae: float | None = None
    r2: float | None = None
    coverage: FitCoverage
    sanity: FitSanity


class SaturationEstimate(BaseModel):
    ceiling_range: tuple[float, float]
    marginal_gain_p20_range: tuple[float, float]
    marginal_gain_p50_range: tuple[float, float]
    confidence: float
    assumptions: list[str]
    evidence_run_ids: list[str] = Field(min_length=1)
    fit: FitReport


class RegimeSignal(BaseModel):
    name: str
    value: Any
    why: str


class RegimeEstimate(BaseModel):
    regime: Literal[
        "DATA_LIMITED",
        "MODEL_LIMITED",
        "NOISE_LIMITED",
        "OPTIMIZATION_LIMITED",
        "UNKNOWN",
    ]
    confidence: float
    signals: list[RegimeSignal]
    evidence_run_ids: list[str] = Field(min_length=1)


class DataPotentialDraft(BaseModel):
    current: float
    low: float
    high: float
    confidence: float
    limiting_factors: list[str]
    assumptions: list[str]
    evidence: dict[str, Any]