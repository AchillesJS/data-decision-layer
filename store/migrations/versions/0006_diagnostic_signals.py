"""add diagnostic_signal_points table

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_signal_points",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column(
            "run_id",
            sa.String(),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("series_name", sa.String(), nullable=False),
        sa.Column("x_kind", sa.String(), nullable=False),
        sa.Column("x_value", sa.Float(), nullable=False),
        sa.Column("y_value", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "run_id",
            "series_name",
            "x_kind",
            "x_value",
            name="uq_diagnostic_signal_points_tenant_run_series_xkind_xvalue",
        ),
    )
    op.create_index(
        "ix_diagnostic_signal_points_tenant_id",
        "diagnostic_signal_points",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_diagnostic_signal_points_run",
        "diagnostic_signal_points",
        ["tenant_id", "run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_diagnostic_signal_points_run", table_name="diagnostic_signal_points"
    )
    op.drop_index(
        "ix_diagnostic_signal_points_tenant_id", table_name="diagnostic_signal_points"
    )
    op.drop_table("diagnostic_signal_points")
