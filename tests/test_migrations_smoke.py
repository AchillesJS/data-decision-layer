from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_migrations_smoke_upgrade_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clean DB -> alembic upgrade head -> all expected tables exist.

    Uses DDW_DB_URL to ensure Alembic and the app share a single DB URL source.
    """

    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "test_app.db"

    monkeypatch.setenv("DDW_DB_URL", f"sqlite+pysqlite:///{db_path}")

    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "store" / "migrations"))

    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite+pysqlite:///{db_path}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    expected = {
        "errors",
        "hypotheses",
        "actions",
        "decision_records",
        "data_potentials",
        "hypothesis_errors",
        "decision_record_errors",
        "decision_record_hypotheses",
        "decision_record_actions",
        "runs",
        "metric_points",
        "runners",
        "jobs",
        "job_log_chunks",
    }

    missing = expected - tables
    assert not missing, f"Missing tables after upgrade head: {sorted(missing)}"