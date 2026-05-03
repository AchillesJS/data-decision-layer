from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ALLOWED_X_KINDS = {"epoch", "step", "time"}
MAX_RUN_REPORT_METRIC_POINTS = 50_000


class MetricPointV1(BaseModel):
    series_name: str = Field(min_length=1)
    x_kind: str = Field(min_length=1)
    x_value: float
    y_value: float = Field(ge=0, le=1)


class ArtifactRefV1(BaseModel):
    kind: str = Field(min_length=1)
    uri: str = Field(min_length=1)
    sha256: str | None = None


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
        has_val = any(
            point.series_name == "val" and point.x_kind in _ALLOWED_X_KINDS
            for point in self.metric_points
        )
        if not has_val:
            raise ValueError(
                'metric_points must include at least one "val" series point with x_kind epoch/step/time'
            )

        grouped: dict[tuple[str, str], list[float]] = {}
        for point in self.metric_points:
            if point.x_kind not in _ALLOWED_X_KINDS:
                raise ValueError("metric_points x_kind must be one of: epoch, step, time")
            grouped.setdefault((point.series_name, point.x_kind), []).append(point.x_value)

        for (series_name, x_kind), values in grouped.items():
            for prev, current in zip(values, values[1:], strict=False):
                if current <= prev:
                    raise ValueError(
                        f"metric_points x_value must be strictly increasing for {series_name}/{x_kind}"
                    )
        return self
