from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FindingKind = Literal[
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

Severity = Literal["info", "warn", "critical"]


class EpochRange(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class Finding(BaseModel):
    """Single curve-level diagnostic signal.

    Findings describe an observation in the metric trajectory; they never claim
    a true cause and never instruct the user. `suggested_checks` are controlled
    investigations the user may perform to validate or refute the signal — each
    item must be framed as 'Check whether X changes Y'. The user remains the
    decision-maker.
    """

    kind: FindingKind
    severity: Severity
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    epoch_range: EpochRange | None = None
    evidence: dict[str, float | int | str] = Field(default_factory=dict)
    suggested_checks: list[str] = Field(default_factory=list)


class DiagnosisReport(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    run_id: str
    metric_name: str
    n_val_points: int
    n_train_points: int
    findings: list[Finding]
    assumptions: list[str] = Field(default_factory=list)


class DiagnosticsInput(BaseModel):
    """Input to diagnostics v1.

    Contract:
    - val_series and train_series are normalized quality scores in [0, 1].
    - Higher is always better.
    - x_values must be strictly increasing.
    - Loss/error/MAE/MSE are unsupported in v1 unless normalized externally
      into a quality score.
    """

    run_id: str
    metric_name: str
    val_series: list[tuple[float, float]] = Field(default_factory=list)
    train_series: list[tuple[float, float]] = Field(default_factory=list)
