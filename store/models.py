from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class JSONText(TypeDecorator):
    """Store JSON as TEXT in SQLite.

    Canonical encoding only: json.dumps/json.loads.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:  # noqa: ANN401
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def process_result_value(self, value: Any, dialect: Any) -> Any:  # noqa: ANN401
        if value is None:
            return None
        return json.loads(value)


class Base(DeclarativeBase):
    pass


# --- Association tables ---

hypothesis_errors = Table(
    "hypothesis_errors",
    Base.metadata,
    Column("hypothesis_id", String, ForeignKey("hypotheses.id"), primary_key=True),
    Column("error_id", String, ForeignKey("errors.id"), primary_key=True),
)

decision_record_errors = Table(
    "decision_record_errors",
    Base.metadata,
    Column(
        "decision_record_id", String, ForeignKey("decision_records.id"), primary_key=True
    ),
    Column("error_id", String, ForeignKey("errors.id"), primary_key=True),
)

decision_record_hypotheses = Table(
    "decision_record_hypotheses",
    Base.metadata,
    Column(
        "decision_record_id", String, ForeignKey("decision_records.id"), primary_key=True
    ),
    Column("hypothesis_id", String, ForeignKey("hypotheses.id"), primary_key=True),
)

decision_record_actions = Table(
    "decision_record_actions",
    Base.metadata,
    Column(
        "decision_record_id", String, ForeignKey("decision_records.id"), primary_key=True
    ),
    Column("action_id", String, ForeignKey("actions.id"), primary_key=True),
)


# --- Tables ---


class ErrorRow(Base):
    __tablename__ = "errors"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)

    y_true: Mapped[str] = mapped_column(String, nullable=False)
    y_pred: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    uncertainty: Mapped[float] = mapped_column(Float, nullable=False)
    repeatability: Mapped[int] = mapped_column(Integer, nullable=False)

    example_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONText, nullable=True)

    hypotheses: Mapped[list[HypothesisRow]] = relationship(
        secondary=hypothesis_errors, back_populates="errors"
    )
    decision_records: Mapped[list[DecisionRecordRow]] = relationship(
        secondary=decision_record_errors, back_populates="errors"
    )

    __table_args__ = (
        Index("ix_errors_tenant_id_status", "tenant_id", "status"),
        Index("ix_errors_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_errors_created_at", "created_at"),
    )


class HypothesisRow(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(140), nullable=False)
    statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    arguments: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    alternatives: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    uncertainty: Mapped[float] = mapped_column(Float, nullable=False)
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONText, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)

    errors: Mapped[list[ErrorRow]] = relationship(
        secondary=hypothesis_errors, back_populates="hypotheses"
    )
    actions: Mapped[list[ActionRow]] = relationship(back_populates="hypothesis")
    decision_records: Mapped[list[DecisionRecordRow]] = relationship(
        secondary=decision_record_hypotheses, back_populates="hypotheses"
    )

    __table_args__ = (
        Index("ix_hypotheses_tenant_id_status", "tenant_id", "status"),
        Index("ix_hypotheses_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_hypotheses_created_at", "created_at"),
    )


class ActionRow(Base):
    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)

    hypothesis_id: Mapped[str | None] = mapped_column(ForeignKey("hypotheses.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    risk_if_false: Mapped[str] = mapped_column(String, nullable=False)
    cost: Mapped[dict[str, Any]] = mapped_column(JSONText, nullable=False)
    expected_artifacts: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)

    hypothesis: Mapped[HypothesisRow | None] = relationship(back_populates="actions")
    decision_records: Mapped[list[DecisionRecordRow]] = relationship(
        secondary=decision_record_actions, back_populates="actions"
    )

    __table_args__ = (
        Index("ix_actions_tenant_id_status", "tenant_id", "status"),
        Index("ix_actions_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_actions_created_at", "created_at"),
    )


class DataPotentialRow(Base):
    __tablename__ = "data_potentials"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)

    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    current: Mapped[float] = mapped_column(Float, nullable=False)
    upper_bound_range: Mapped[list[float] | None] = mapped_column(JSONText, nullable=True)
    scenarios: Mapped[dict[str, list[float]] | None] = mapped_column(JSONText, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    limiting_factors: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    assumptions: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    evidence_error_ids: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    evidence_run_ids: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    decision_records: Mapped[list[DecisionRecordRow]] = relationship(back_populates="potential")

    __table_args__ = (
        Index("ix_data_potentials_tenant_id_status", "tenant_id", "status"),
        Index("ix_data_potentials_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_data_potentials_created_at", "created_at"),
    )


class DecisionRecordRow(Base):
    __tablename__ = "decision_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    made_by: Mapped[str] = mapped_column(String(120), nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    potential_id: Mapped[str | None] = mapped_column(ForeignKey("data_potentials.id"), nullable=True)
    potential: Mapped[DataPotentialRow | None] = relationship(back_populates="decision_records")

    errors: Mapped[list[ErrorRow]] = relationship(
        secondary=decision_record_errors, back_populates="decision_records"
    )
    hypotheses: Mapped[list[HypothesisRow]] = relationship(
        secondary=decision_record_hypotheses, back_populates="decision_records"
    )
    actions: Mapped[list[ActionRow]] = relationship(
        secondary=decision_record_actions, back_populates="decision_records"
    )

    __table_args__ = (
        Index("ix_decision_records_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_decision_records_created_at", "created_at"),
    )


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    external_run_id: Mapped[str] = mapped_column(String, nullable=False, default=lambda: f"legacy:{uuid4()}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    status: Mapped[str] = mapped_column(String, nullable=False)
    dataset_version: Mapped[str | None] = mapped_column(String, nullable=True)
    dataset_size: Mapped[float] = mapped_column(Float, nullable=False)
    model_tag: Mapped[str] = mapped_column(String, nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    budget_kind: Mapped[str] = mapped_column(String, nullable=False)
    budget_value: Mapped[float] = mapped_column(Float, nullable=False)

    metric_name: Mapped[str] = mapped_column(String, nullable=False)
    split: Mapped[str | None] = mapped_column(String, nullable=True)
    metric_final: Mapped[float] = mapped_column(Float, nullable=False)

    config_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String, nullable=True)

    metric_points: Mapped[list[MetricPointRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_runs_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_runs_tenant_id_model_tag", "tenant_id", "model_tag"),
        Index("ix_runs_tenant_id_metric_name", "tenant_id", "metric_name"),
        Index("ix_runs_tenant_id_dataset_version", "tenant_id", "dataset_version"),
        UniqueConstraint("tenant_id", "external_run_id", name="uq_runs_tenant_external_run_id"),
    )


class MetricPointRow(Base):
    __tablename__ = "metric_points"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False)
    series_name: Mapped[str] = mapped_column(String, nullable=False)
    x_kind: Mapped[str] = mapped_column(String, nullable=False)
    x_value: Mapped[float] = mapped_column(Float, nullable=False)
    y_value: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    run: Mapped[RunRow] = relationship(back_populates="metric_points")

    __table_args__ = (Index("ix_metric_points_tenant_id_run_id", "tenant_id", "run_id"),)


class DiagnosticSignalPointRow(Base):
    __tablename__ = "diagnostic_signal_points"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    series_name: Mapped[str] = mapped_column(String, nullable=False)
    x_kind: Mapped[str] = mapped_column(String, nullable=False)
    x_value: Mapped[float] = mapped_column(Float, nullable=False)
    y_value: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "run_id",
            "series_name",
            "x_kind",
            "x_value",
            name="uq_diagnostic_signal_points_tenant_run_series_xkind_xvalue",
        ),
        Index("ix_diagnostic_signal_points_run", "tenant_id", "run_id"),
    )


class RunnerRow(Base):
    __tablename__ = "runners"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    tags_json: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    token_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)

    __table_args__ = (
        Index("ix_runners_tenant_id_status", "tenant_id", "status"),
        Index("ix_runners_tenant_id_last_seen_at", "tenant_id", "last_seen_at"),
    )


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    requested_tags_json: Mapped[list[str] | None] = mapped_column(JSONText, nullable=True)
    runner_id: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    workdir: Mapped[str | None] = mapped_column(Text, nullable=True)
    env_json: Mapped[dict[str, str] | None] = mapped_column(JSONText, nullable=True)
    timeout_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), nullable=True)

    __table_args__ = (
        Index("ix_jobs_tenant_id_status", "tenant_id", "status"),
        Index("ix_jobs_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_jobs_tenant_id_runner_id", "tenant_id", "runner_id"),
    )


class JobLogChunkRow(Base):
    __tablename__ = "job_log_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    stream: Mapped[str] = mapped_column(String, nullable=False)
    chunk: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "job_id", "seq", name="uq_job_log_chunks_tenant_job_seq"),
        Index("ix_job_log_chunks_tenant_id_job_id_seq", "tenant_id", "job_id", "seq"),
    )
