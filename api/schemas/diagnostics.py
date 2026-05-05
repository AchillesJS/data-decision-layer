from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FindingKindRead = Literal[
    "insufficient_data",
    "invalid_series",
    "unsupported_metric_scale",
    "cold_start_failure",
    "plateau_late",
    "overfitting_divergence",
    "late_collapse",
    "high_variance",
    "train_underfitting",
    "premature_saturation",
    "series_was_reordered",
    "vanishing_gradient",
    "exploding_gradient",
    "gradient_norm_decay",
    "learning_rate_too_high",
    "learning_rate_too_low",
    "weight_norm_explosion",
]

SeverityRead = Literal["info", "warn", "critical"]


class EpochRangeRead(BaseModel):
    start: float
    end: float


class FindingRead(BaseModel):
    kind: FindingKindRead
    severity: SeverityRead
    title: str
    description: str
    epoch_range: EpochRangeRead | None = None
    evidence: dict[str, float | int | str] = Field(default_factory=dict)
    suggested_checks: list[str] = Field(default_factory=list)


class DiagnosisReportRead(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    run_id: str
    metric_name: str
    n_val_points: int
    n_train_points: int
    findings: list[FindingRead]
    assumptions: list[str] = Field(default_factory=list)
