from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from api.schemas.run_report import RunReportPayload


class RunnerRegisterRequest(BaseModel):
    name: str | None = None
    tags: list[str] = Field(default_factory=list)


class RunnerRegisterResponse(BaseModel):
    runner_id: str
    runner_token_plain_once: str


class RunnerRead(BaseModel):
    id: str
    name: str | None
    tags: list[str]
    status: str
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class JobCreateRequest(BaseModel):
    command: str = Field(min_length=1)
    requested_tags: list[str] | None = None
    workdir: str | None = None
    env: dict[str, str] | None = None
    timeout_sec: int | None = Field(default=None, gt=0)


class JobRead(BaseModel):
    id: str
    status: str
    requested_tags: list[str] | None
    runner_id: str | None
    command: str
    workdir: str | None
    env: dict[str, str] | None
    timeout_sec: int | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    exit_code: int | None
    error_message: str | None
    run_id: str | None


class JobClaimRequest(BaseModel):
    tags_filter: list[str] | None = None


class JobClaimResponse(BaseModel):
    job: JobRead
    lease_token: str
    lease_expires_at: datetime


class LogChunkIn(BaseModel):
    seq: int = Field(ge=0)
    stream: Literal["stdout", "stderr"]
    chunk: str = Field(max_length=64_000)
    ts: datetime | None = None


class LogsAppendRequest(BaseModel):
    chunks: list[LogChunkIn] = Field(min_length=1, max_length=1000)


class JobLogChunkRead(BaseModel):
    id: str
    job_id: str
    seq: int
    ts: datetime
    stream: str
    chunk: str = Field(max_length=64_000)


class JobCompleteRequest(BaseModel):
    status: Literal["SUCCEEDED", "FAILED", "CANCELED"]
    exit_code: int | None = None
    error_message: str | None = None
    run_report: RunReportPayload | None = None


class JobCompleteResponse(BaseModel):
    job_id: str
    status: str
    run_id: str | None
