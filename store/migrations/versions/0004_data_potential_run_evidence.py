"""add evidence_run_ids to data_potentials

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add evidence_run_ids JSON column to data_potentials.

    Existing rows get '[]' as default. server_default kept for forward-compat.
    """

    with op.batch_alter_table("data_potentials") as batch:
        batch.add_column(
            sa.Column(
                "evidence_run_ids",
                sa.Text(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("data_potentials") as batch:
        batch.drop_column("evidence_run_ids")
