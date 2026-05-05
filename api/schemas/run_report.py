from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from contracts.run_report import (
    ArtifactRefV1,
    DiagnosticSeriesPointV1,
    MetricPointV1,
    RunMetaV1,
    RunReportV1,
    RunReportV2,
)

RunReportPayload = Annotated[RunReportV1 | RunReportV2, Field(discriminator="schema_version")]


class RunReportIngestResponse(BaseModel):
    run_id: str
    external_run_id: str
    created: bool


__all__ = [
    "ArtifactRefV1",
    "DiagnosticSeriesPointV1",
    "MetricPointV1",
    "RunMetaV1",
    "RunReportV1",
    "RunReportPayload",
    "RunReportV2",
    "RunReportIngestResponse",
]
