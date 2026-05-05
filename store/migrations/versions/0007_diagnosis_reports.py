"""add diagnosis_reports table

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "diagnosis_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("engine_version", sa.String(), nullable=False),
        sa.Column("metric_name", sa.String(), nullable=False),
        sa.Column("n_val_points", sa.Integer(), nullable=False),
        sa.Column("n_train_points", sa.Integer(), nullable=False),
        sa.Column("findings_json", sa.Text(), nullable=False),
        sa.Column("assumptions_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "engine_version",
            name="uq_diagnosis_reports_tenant_run_engine",
        ),
    )
    op.create_index(
        "ix_diagnosis_reports_tenant_id",
        "diagnosis_reports",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_diagnosis_reports_run",
        "diagnosis_reports",
        ["tenant_id", "run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_diagnosis_reports_run", table_name="diagnosis_reports")
    op.drop_index("ix_diagnosis_reports_tenant_id", table_name="diagnosis_reports")
    op.drop_table("diagnosis_reports")
