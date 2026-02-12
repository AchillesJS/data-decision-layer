from __future__ import annotations

import json
from datetime import datetime
from typing import Any

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
    Column("decision_record_id", String, ForeignKey("decision_records.id"), primary_key=True),
    Column("error_id", String, ForeignKey("errors.id"), primary_key=True),
)

decision_record_hypotheses = Table(
    "decision_record_hypotheses",
    Base.metadata,
    Column("decision_record_id", String, ForeignKey("decision_records.id"), primary_key=True),
    Column("hypothesis_id", String, ForeignKey("hypotheses.id"), primary_key=True),
)

decision_record_actions = Table(
    "decision_record_actions",
    Base.metadata,
    Column("decision_record_id", String, ForeignKey("decision_records.id"), primary_key=True),
    Column("action_id", String, ForeignKey("actions.id"), primary_key=True),
)


# --- Tables ---


class ErrorRow(Base):
    __tablename__ = "errors"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # TODO: add indexes for project_id/model_id/run_id when they exist in core

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
        Index("ix_errors_created_at", "created_at"),
    )


class HypothesisRow(Base):
    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # TODO: add indexes for project_id/model_id/run_id when they exist in core

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
        Index("ix_hypotheses_created_at", "created_at"),
    )


class ActionRow(Base):
    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # TODO: add indexes for project_id/model_id/run_id when they exist in core

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
        Index("ix_actions_created_at", "created_at"),
    )


class DataPotentialRow(Base):
    __tablename__ = "data_potentials"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # TODO: add indexes for project_id/model_id/run_id when they exist in core

    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    current: Mapped[float] = mapped_column(Float, nullable=False)
    upper_bound_range: Mapped[list[float] | None] = mapped_column(JSONText, nullable=True)
    scenarios: Mapped[dict[str, list[float]] | None] = mapped_column(JSONText, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    limiting_factors: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    assumptions: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    evidence_error_ids: Mapped[list[str]] = mapped_column(JSONText, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    decision_records: Mapped[list[DecisionRecordRow]] = relationship(back_populates="potential")

    __table_args__ = (
        Index("ix_data_potentials_created_at", "created_at"),
    )


class DecisionRecordRow(Base):
    __tablename__ = "decision_records"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    # TODO: add indexes for project_id/model_id/run_id when they exist in core

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
        Index("ix_decision_records_created_at", "created_at"),
    )
