from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ALLOWED_X_KINDS = {"epoch", "step", "time"}
MAX_RUN_REPORT_METRIC_POINTS = 50_000


KNOWN_DIAGNOSTIC_SERIES = frozenset(
    {
        "loss_train",
        "loss_val",
        "grad_norm_global",
        "grad_norm_first_layer",
        "grad_norm_last_layer",
        "weight_norm_global",
        "lr",
        "param_update_ratio",
    }
)


class MetricPointV1(BaseModel):
    series_name: str = Field(min_length=1)
    x_kind: str = Field(min_length=1)
    x_value: float
    y_value: float = Field(ge=0, le=1)


class ArtifactRefV1(BaseModel):
    kind: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: str | None = None


class DiagnosticSeriesPointV1(BaseModel):
    """Unbounded diagnostic signal point.

    Unlike MetricPointV1, y_value is not restricted to [0, 1].
    Intended for loss, gradient norms, learning rate, weight norms, etc.
    """

    series_name: str = Field(min_length=1)
    x_kind: str = Field(min_length=1)
    x_value: float
    y_value: float


class RunMetaV1(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_tag: str = Field(min_length=1)
    dataset_version: str | None = None
    dataset_size: float = Field(gt=0)
    seed: int | None = None
    budget_kind: Literal["steps", "epochs", "time_sec"]
    budget_value: float = Field(gt=0)
    metric_name: str = Field(min_length=1)
    split: str | None = None
    metric_final: float = Field(ge=0, le=1)
    status: Literal["SUCCEEDED", "FAILED"]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    config_hash: str | None = None
    git_commit: str | None = None


def _validate_metric_points_invariants(metric_points: list[MetricPointV1]) -> None:
    has_val = any(
        point.series_name == "val" and point.x_kind in _ALLOWED_X_KINDS
        for point in metric_points
    )
    if not has_val:
        raise ValueError(
            'metric_points must include at least one "val" series point with x_kind epoch/step/time'
        )

    grouped: dict[tuple[str, str], list[float]] = {}
    for point in metric_points:
        if point.x_kind not in _ALLOWED_X_KINDS:
            raise ValueError("metric_points x_kind must be one of: epoch, step, time")
        grouped.setdefault((point.series_name, point.x_kind), []).append(point.x_value)

    for (series_name, x_kind), values in grouped.items():
        for prev, current in zip(values, values[1:], strict=False):
            if current <= prev:
                raise ValueError(
                    f"metric_points x_value must be strictly increasing for {series_name}/{x_kind}"
                )


def _validate_diagnostic_signals_increasing(
    diagnostic_signals: list[DiagnosticSeriesPointV1],
) -> None:
    grouped: dict[tuple[str, str], list[float]] = {}
    for p in diagnostic_signals:
        grouped.setdefault((p.series_name, p.x_kind), []).append(p.x_value)

    for key, xs in grouped.items():
        for prev, curr in zip(xs, xs[1:], strict=False):
            if curr <= prev:
                raise ValueError(
                    f"diagnostic_signals x_value must be strictly increasing for {key[0]}/{key[1]}"
                )


class RunReportV1(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    schema_version: Literal[1]
    external_run_id: str = Field(min_length=1)
    run: RunMetaV1
    metric_points: list[MetricPointV1] = Field(
        min_length=1,
        max_length=MAX_RUN_REPORT_METRIC_POINTS,
    )
    artifacts: list[ArtifactRefV1] | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_metric_points(self) -> RunReportV1:
        _validate_metric_points_invariants(self.metric_points)
        return self


class RunReportV2(BaseModel):
    """Extends RunReport v1 with optional diagnostic_signals.

    V1 reports remain valid as RunReportV1. V2 reports must use schema_version=2.
    If diagnostic_signals is absent, behavior is identical to V1.
    """

    model_config = ConfigDict(protected_namespaces=())

    schema_version: Literal[2]
    external_run_id: str = Field(min_length=1)
    run: RunMetaV1
    metric_points: list[MetricPointV1] = Field(
        min_length=1,
        max_length=MAX_RUN_REPORT_METRIC_POINTS,
    )
    artifacts: list[ArtifactRefV1] | None = None
    notes: str | None = None
    diagnostic_signals: list[DiagnosticSeriesPointV1] = Field(
        default_factory=list,
        max_length=MAX_RUN_REPORT_METRIC_POINTS,
    )

    @model_validator(mode="after")
    def validate_metric_points(self) -> RunReportV2:
        _validate_metric_points_invariants(self.metric_points)
        return self

    @model_validator(mode="after")
    def validate_diagnostic_signals(self) -> RunReportV2:
        _validate_diagnostic_signals_increasing(self.diagnostic_signals)
        return self
