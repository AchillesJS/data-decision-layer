"""add jobs runners and run report idempotency

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-03

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("external_run_id", sa.Text(), nullable=True))

    op.execute("UPDATE runs SET external_run_id = 'legacy:' || id WHERE external_run_id IS NULL")

    with op.batch_alter_table("runs") as batch:
        batch.alter_column("external_run_id", existing_type=sa.Text(), nullable=False)
        batch.create_unique_constraint(
            "uq_runs_tenant_external_run_id", ["tenant_id", "external_run_id"]
        )

    op.create_table(
        "runners",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
    )
    op.create_index("ix_runners_tenant_id", "runners", ["tenant_id"], unique=False)
    op.create_index("ix_runners_tenant_id_status", "runners", ["tenant_id", "status"], unique=False)
    op.create_index(
        "ix_runners_tenant_id_last_seen_at", "runners", ["tenant_id", "last_seen_at"], unique=False
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_tags_json", sa.Text(), nullable=True),
        sa.Column("runner_id", sa.Text(), nullable=True),
        sa.Column("lease_token_hash", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("workdir", sa.Text(), nullable=True),
        sa.Column("env_json", sa.Text(), nullable=True),
        sa.Column("timeout_sec", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("run_id", sa.String(), sa.ForeignKey("runs.id"), nullable=True),
    )
    op.create_index("ix_jobs_tenant_id", "jobs", ["tenant_id"], unique=False)
    op.create_index("ix_jobs_status", "jobs", ["status"], unique=False)
    op.create_index("ix_jobs_tenant_id_status", "jobs", ["tenant_id", "status"], unique=False)
    op.create_index("ix_jobs_tenant_id_created_at", "jobs", ["tenant_id", "created_at"], unique=False)
    op.create_index("ix_jobs_tenant_id_runner_id", "jobs", ["tenant_id", "runner_id"], unique=False)

    op.create_table(
        "job_log_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("job_id", sa.String(), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=False), nullable=False),
        sa.Column("stream", sa.String(), nullable=False),
        sa.Column("chunk", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "job_id", "seq", name="uq_job_log_chunks_tenant_job_seq"),
    )
    op.create_index("ix_job_log_chunks_tenant_id", "job_log_chunks", ["tenant_id"], unique=False)
    op.create_index(
        "ix_job_log_chunks_tenant_id_job_id_seq",
        "job_log_chunks",
        ["tenant_id", "job_id", "seq"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_job_log_chunks_tenant_id_job_id_seq", table_name="job_log_chunks")
    op.drop_index("ix_job_log_chunks_tenant_id", table_name="job_log_chunks")
    op.drop_table("job_log_chunks")
    op.drop_index("ix_jobs_tenant_id_runner_id", table_name="jobs")
    op.drop_index("ix_jobs_tenant_id_created_at", table_name="jobs")
    op.drop_index("ix_jobs_tenant_id_status", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_tenant_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_runners_tenant_id_last_seen_at", table_name="runners")
    op.drop_index("ix_runners_tenant_id_status", table_name="runners")
    op.drop_index("ix_runners_tenant_id", table_name="runners")
    op.drop_table("runners")
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("uq_runs_tenant_external_run_id", type_="unique")
        batch.drop_column("external_run_id")
