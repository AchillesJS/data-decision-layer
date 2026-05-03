"""add runs and metric_points

Revision ID: 0003
Revises: 0002
Create Date: 2026-02-21

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "runs",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("dataset_version", sa.String(), nullable=True),
        sa.Column("dataset_size", sa.Float(), nullable=False),
        sa.Column("model_tag", sa.String(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("budget_kind", sa.String(), nullable=False),
        sa.Column("budget_value", sa.Float(), nullable=False),
        sa.Column("metric_name", sa.String(), nullable=False),
        sa.Column("split", sa.String(), nullable=True),
        sa.Column("metric_final", sa.Float(), nullable=False),
        sa.Column("config_hash", sa.String(), nullable=True),
        sa.Column("git_commit", sa.String(), nullable=True),
    )

    op.create_index("ix_runs_tenant_id", "runs", ["tenant_id"], unique=False)
    op.create_index(
        "ix_runs_tenant_id_created_at", "runs", ["tenant_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_runs_tenant_id_model_tag", "runs", ["tenant_id", "model_tag"], unique=False
    )
    op.create_index(
        "ix_runs_tenant_id_metric_name", "runs", ["tenant_id", "metric_name"], unique=False
    )
    op.create_index(
        "ix_runs_tenant_id_dataset_version",
        "runs",
        ["tenant_id", "dataset_version"],
        unique=False,
    )

    op.create_table(
        "metric_points",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("series_name", sa.String(), nullable=False),
        sa.Column("x_kind", sa.String(), nullable=False),
        sa.Column("x_value", sa.Float(), nullable=False),
        sa.Column("y_value", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
    )

    op.create_index("ix_metric_points_tenant_id", "metric_points", ["tenant_id"], unique=False)
    op.create_index(
        "ix_metric_points_tenant_id_run_id",
        "metric_points",
        ["tenant_id", "run_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index("ix_metric_points_tenant_id_run_id", table_name="metric_points")
    op.drop_index("ix_metric_points_tenant_id", table_name="metric_points")
    op.drop_table("metric_points")

    op.drop_index("ix_runs_tenant_id_dataset_version", table_name="runs")
    op.drop_index("ix_runs_tenant_id_metric_name", table_name="runs")
    op.drop_index("ix_runs_tenant_id_model_tag", table_name="runs")
    op.drop_index("ix_runs_tenant_id_created_at", table_name="runs")
    op.drop_index("ix_runs_tenant_id", table_name="runs")
    op.drop_table("runs")
