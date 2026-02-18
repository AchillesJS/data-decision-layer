"""init

Revision ID: 0001
Revises:
Create Date: 2026-02-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# NOTE: migrations may import only store.* (no core/use_cases/api)
from store.models import JSONText

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "errors",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("y_true", sa.String(), nullable=False),
        sa.Column("y_pred", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("uncertainty", sa.Float(), nullable=False),
        sa.Column("repeatability", sa.Integer(), nullable=False),
        sa.Column("example_ref", sa.String(), nullable=True),
        sa.Column("context", JSONText(), nullable=True),
    )
    op.create_index("ix_errors_status", "errors", ["status"], unique=False)
    op.create_index("ix_errors_created_at", "errors", ["created_at"], unique=False)

    op.create_table(
        "hypotheses",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("statement", sa.Text(), nullable=True),
        sa.Column("arguments", JSONText(), nullable=False),
        sa.Column("alternatives", JSONText(), nullable=False),
        sa.Column("uncertainty", sa.Float(), nullable=False),
        sa.Column("scope", JSONText(), nullable=True),
        sa.Column("tags", JSONText(), nullable=False),
    )
    op.create_index("ix_hypotheses_status", "hypotheses", ["status"], unique=False)
    op.create_index("ix_hypotheses_created_at", "hypotheses", ["created_at"], unique=False)

    op.create_table(
        "actions",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("hypothesis_id", sa.String(), sa.ForeignKey("hypotheses.id"), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("risk_if_false", sa.String(), nullable=False),
        sa.Column("cost", JSONText(), nullable=False),
        sa.Column("expected_artifacts", JSONText(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("cancel_reason", sa.String(length=240), nullable=True),
    )
    op.create_index("ix_actions_status", "actions", ["status"], unique=False)
    op.create_index("ix_actions_created_at", "actions", ["created_at"], unique=False)

    op.create_table(
        "data_potentials",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("metric_name", sa.String(length=64), nullable=False),
        sa.Column("current", sa.Float(), nullable=False),
        sa.Column("upper_bound_range", JSONText(), nullable=True),
        sa.Column("scenarios", JSONText(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("limiting_factors", JSONText(), nullable=False),
        sa.Column("assumptions", JSONText(), nullable=False),
        sa.Column("evidence_error_ids", JSONText(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_data_potentials_status",
        "data_potentials",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_data_potentials_created_at",
        "data_potentials",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "decision_records",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("made_by", sa.String(length=120), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("potential_id", sa.String(), sa.ForeignKey("data_potentials.id"), nullable=True),
    )
    op.create_index(
        "ix_decision_records_created_at",
        "decision_records",
        ["created_at"],
        unique=False,
    )

    # --- M2M association tables ---
    op.create_table(
        "hypothesis_errors",
        sa.Column(
            "hypothesis_id",
            sa.String(),
            sa.ForeignKey("hypotheses.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "error_id",
            sa.String(),
            sa.ForeignKey("errors.id"),
            primary_key=True,
            nullable=False,
        ),
    )

    op.create_table(
        "decision_record_errors",
        sa.Column(
            "decision_record_id",
            sa.String(),
            sa.ForeignKey("decision_records.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "error_id",
            sa.String(),
            sa.ForeignKey("errors.id"),
            primary_key=True,
            nullable=False,
        ),
    )

    op.create_table(
        "decision_record_hypotheses",
        sa.Column(
            "decision_record_id",
            sa.String(),
            sa.ForeignKey("decision_records.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "hypothesis_id",
            sa.String(),
            sa.ForeignKey("hypotheses.id"),
            primary_key=True,
            nullable=False,
        ),
    )

    op.create_table(
        "decision_record_actions",
        sa.Column(
            "decision_record_id",
            sa.String(),
            sa.ForeignKey("decision_records.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "action_id",
            sa.String(),
            sa.ForeignKey("actions.id"),
            primary_key=True,
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""

    # Drop association tables first (depend on base tables).
    op.drop_table("decision_record_actions")
    op.drop_table("decision_record_hypotheses")
    op.drop_table("decision_record_errors")
    op.drop_table("hypothesis_errors")

    # Drop main tables (reverse dependency order).
    op.drop_index("ix_decision_records_created_at", table_name="decision_records")
    op.drop_table("decision_records")

    op.drop_index("ix_data_potentials_created_at", table_name="data_potentials")
    op.drop_index("ix_data_potentials_status", table_name="data_potentials")
    op.drop_table("data_potentials")

    op.drop_index("ix_actions_created_at", table_name="actions")
    op.drop_index("ix_actions_status", table_name="actions")
    op.drop_table("actions")

    op.drop_index("ix_hypotheses_created_at", table_name="hypotheses")
    op.drop_index("ix_hypotheses_status", table_name="hypotheses")
    op.drop_table("hypotheses")

    op.drop_index("ix_errors_created_at", table_name="errors")
    op.drop_index("ix_errors_status", table_name="errors")
    op.drop_table("errors")
