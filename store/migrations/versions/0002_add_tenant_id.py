"""add tenant_id to base tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-02-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DEFAULT_TENANT = "default"


def _default_tenant_sql():
    # SQLite needs quoted string literal for DEFAULT.
    return sa.text(f"'{_DEFAULT_TENANT}'")


def _backfill(table: str) -> None:
    op.execute(
        sa.text(f"UPDATE {table} SET tenant_id = :t WHERE tenant_id IS NULL").bindparams(
            t=_DEFAULT_TENANT
        )
    )


def upgrade() -> None:
    """Upgrade schema."""

    # errors
    with op.batch_alter_table("errors") as batch_op:
        batch_op.add_column(
            sa.Column(
                "tenant_id",
                sa.String(),
                nullable=False,
                server_default=_default_tenant_sql(),
            )
        )
        batch_op.create_index("ix_errors_tenant_id", ["tenant_id"], unique=False)
        batch_op.create_index("ix_errors_tenant_id_status", ["tenant_id", "status"], unique=False)
        batch_op.create_index(
            "ix_errors_tenant_id_created_at", ["tenant_id", "created_at"], unique=False
        )
    _backfill("errors")

    # hypotheses
    with op.batch_alter_table("hypotheses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "tenant_id",
                sa.String(),
                nullable=False,
                server_default=_default_tenant_sql(),
            )
        )
        batch_op.create_index("ix_hypotheses_tenant_id", ["tenant_id"], unique=False)
        batch_op.create_index(
            "ix_hypotheses_tenant_id_status", ["tenant_id", "status"], unique=False
        )
        batch_op.create_index(
            "ix_hypotheses_tenant_id_created_at", ["tenant_id", "created_at"], unique=False
        )
    _backfill("hypotheses")

    # actions
    with op.batch_alter_table("actions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "tenant_id",
                sa.String(),
                nullable=False,
                server_default=_default_tenant_sql(),
            )
        )
        batch_op.create_index("ix_actions_tenant_id", ["tenant_id"], unique=False)
        batch_op.create_index("ix_actions_tenant_id_status", ["tenant_id", "status"], unique=False)
        batch_op.create_index(
            "ix_actions_tenant_id_created_at", ["tenant_id", "created_at"], unique=False
        )
    _backfill("actions")

    # data_potentials
    with op.batch_alter_table("data_potentials") as batch_op:
        batch_op.add_column(
            sa.Column(
                "tenant_id",
                sa.String(),
                nullable=False,
                server_default=_default_tenant_sql(),
            )
        )
        batch_op.create_index("ix_data_potentials_tenant_id", ["tenant_id"], unique=False)
        batch_op.create_index(
            "ix_data_potentials_tenant_id_status", ["tenant_id", "status"], unique=False
        )
        batch_op.create_index(
            "ix_data_potentials_tenant_id_created_at", ["tenant_id", "created_at"], unique=False
        )
    _backfill("data_potentials")

    # decision_records
    with op.batch_alter_table("decision_records") as batch_op:
        batch_op.add_column(
            sa.Column(
                "tenant_id",
                sa.String(),
                nullable=False,
                server_default=_default_tenant_sql(),
            )
        )
        batch_op.create_index("ix_decision_records_tenant_id", ["tenant_id"], unique=False)
        batch_op.create_index(
            "ix_decision_records_tenant_id_created_at", ["tenant_id", "created_at"], unique=False
        )
    _backfill("decision_records")


def downgrade() -> None:
    """Downgrade schema."""

    with op.batch_alter_table("decision_records") as batch_op:
        batch_op.drop_index("ix_decision_records_tenant_id_created_at")
        batch_op.drop_index("ix_decision_records_tenant_id")
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("data_potentials") as batch_op:
        batch_op.drop_index("ix_data_potentials_tenant_id_created_at")
        batch_op.drop_index("ix_data_potentials_tenant_id_status")
        batch_op.drop_index("ix_data_potentials_tenant_id")
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("actions") as batch_op:
        batch_op.drop_index("ix_actions_tenant_id_created_at")
        batch_op.drop_index("ix_actions_tenant_id_status")
        batch_op.drop_index("ix_actions_tenant_id")
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("hypotheses") as batch_op:
        batch_op.drop_index("ix_hypotheses_tenant_id_created_at")
        batch_op.drop_index("ix_hypotheses_tenant_id_status")
        batch_op.drop_index("ix_hypotheses_tenant_id")
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("errors") as batch_op:
        batch_op.drop_index("ix_errors_tenant_id_created_at")
        batch_op.drop_index("ix_errors_tenant_id_status")
        batch_op.drop_index("ix_errors_tenant_id")
        batch_op.drop_column("tenant_id")
