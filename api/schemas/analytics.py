from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    evidence_run_count_total: int = Field(ge=1)
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
    evidence_run_count_total: int = Field(ge=1)


class DataPotentialDraft(BaseModel):
    current: float
    low: float
    high: float
    confidence: float
    limiting_factors: list[str]
    assumptions: list[str]
    evidence: dict[str, Any]


class LearningAnalysisRead(BaseModel):
    saturation_estimate: SaturationEstimate
    regime_estimate: RegimeEstimate
    potential_draft: DataPotentialDraft


class SaveFromDraftRequest(BaseModel):
    """Re-runs analytics for the given query and persists the resulting draft
    as a DataPotential (status=ESTIMATED).

    The endpoint owns the analytics call to guarantee evidence_run_ids
    are coherent with the current run set inside the tenant.
    """

    model_config = ConfigDict(protected_namespaces=())

    model_tag: str = Field(min_length=1)
    metric_name: str = Field(min_length=1)
    x_kind: Literal["dataset_size", "budget"]
    dataset_version: str | None = None
    split: str | None = None
    budget_kind: str | None = None
    notes: str | None = Field(default=None, max_length=2_000)
