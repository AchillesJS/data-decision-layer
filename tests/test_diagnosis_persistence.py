from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.deps import get_repo
from api.main import create_app
from store.models import Base
from store.repository import Repository


@pytest.fixture()
def repo() -> Repository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Repository(
        engine=engine,
        SessionLocal=sessionmaker(bind=engine, expire_on_commit=False, future=True),
    )


@pytest.fixture()
def client(repo: Repository) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    return TestClient(app)


def _h(tenant: str = "tenantA") -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "Content-Type": "application/json"}


def _register_runner(client: TestClient, tenant: str = "tenantA") -> tuple[str, str]:
    response = client.post(
        "/api/v1/runners/register",
        headers=_h(tenant),
        json={"name": "runner-1", "tags": ["gpu"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return str(body["runner_id"]), str(body["runner_token_plain_once"])


def _create_job(client: TestClient, tenant: str = "tenantA") -> str:
    response = client.post(
        "/api/v1/jobs",
        headers=_h(tenant),
        json={"command": "python train.py", "requested_tags": ["gpu"]},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _claim_job(client: TestClient, runner_id: str, runner_token: str, tenant: str = "tenantA") -> dict[str, Any]:
    response = client.post(
        "/api/v1/jobs/claim",
        headers={**_h(tenant), "X-Runner-Id": runner_id, "X-Runner-Token": runner_token},
        json={},
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def _learning_curve_metric_points() -> list[dict[str, Any]]:
    pts: list[dict[str, Any]] = []
    for i, y in enumerate([0.30, 0.40, 0.50, 0.55, 0.60, 0.62, 0.64, 0.65], start=1):
        pts.append({"series_name": "val", "x_kind": "epoch", "x_value": float(i), "y_value": y})
    for i, y in enumerate([0.32, 0.42, 0.52, 0.57, 0.62, 0.64, 0.66, 0.67], start=1):
        pts.append({"series_name": "train", "x_kind": "epoch", "x_value": float(i), "y_value": y})
    return pts


def _v2_report(external: str, *, with_signals: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": 2,
        "external_run_id": external,
        "run": {
            "model_tag": "m1",
            "dataset_version": "v1",
            "dataset_size": 100.0,
            "seed": 7,
            "budget_kind": "epochs",
            "budget_value": 8.0,
            "metric_name": "accuracy",
            "split": "val",
            "metric_final": 0.65,
            "status": "SUCCEEDED",
            "config_hash": "abc",
            "git_commit": "def",
        },
        "metric_points": _learning_curve_metric_points(),
    }
    if with_signals:
        body["diagnostic_signals"] = [
            {"series_name": "grad_norm_global", "x_kind": "step", "x_value": float(i), "y_value": 1.0}
            for i in range(1, 11)
        ]
    return body


def _complete(
    client: TestClient,
    job_id: str,
    runner_id: str,
    runner_token: str,
    lease_token: str,
    report: dict[str, Any] | None,
    tenant: str = "tenantA",
) -> Any:
    return client.post(
        f"/api/v1/jobs/{job_id}/complete",
        headers={
            **_h(tenant),
            "X-Runner-Id": runner_id,
            "X-Runner-Token": runner_token,
            "X-Lease-Token": lease_token,
        },
        json={"status": "SUCCEEDED", "exit_code": 0, "run_report": report},
    )


def _complete_with_report(client: TestClient, repo: Repository, external: str = "ext-1") -> str:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)
    response = _complete(client, job_id, runner_id, token, claim["lease_token"], _v2_report(external))
    assert response.status_code == 200, response.text
    return str(response.json()["run_id"])


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


def test_diagnosis_report_persisted_on_job_complete(client: TestClient, repo: Repository) -> None:
    run_id = _complete_with_report(client, repo)
    rows = repo.list_diagnosis_reports("tenantA", run_id)
    assert len(rows) == 1
    assert rows[0].engine_version == "v1.0+v2.0"
    assert rows[0].metric_name == "accuracy"


def test_diagnosis_failure_does_not_fail_job(client: TestClient, repo: Repository) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)

    with patch(
        "use_cases.jobs.diagnose_and_store_run_use_case",
        side_effect=RuntimeError("boom"),
    ):
        response = _complete(
            client, job_id, runner_id, token, claim["lease_token"], _v2_report("ext-fail")
        )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    # Run must exist; no diagnosis report stored.
    assert repo.get_run("tenantA", run_id) is not None
    assert repo.list_diagnosis_reports("tenantA", run_id) == []


def test_get_diagnostics_returns_stored_report(client: TestClient, repo: Repository) -> None:
    run_id = _complete_with_report(client, repo)
    response = client.get(f"/api/v1/diagnostics/runs/{run_id}", headers=_h())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["run_id"] == run_id
    # Match the persisted assumptions exactly (the recompute path may differ).
    stored = repo.get_diagnosis_report("tenantA", run_id)
    assert stored is not None
    assert data["assumptions"] == stored.assumptions_json


def test_force_recompute_bypasses_storage(client: TestClient, repo: Repository) -> None:
    run_id = _complete_with_report(client, repo)
    initial = repo.list_diagnosis_reports("tenantA", run_id)
    assert len(initial) == 1
    initial_created_at = initial[0].created_at

    response = client.get(
        f"/api/v1/diagnostics/runs/{run_id}",
        headers=_h(),
        params={"force_recompute": "true"},
    )
    assert response.status_code == 200, response.text

    after = repo.list_diagnosis_reports("tenantA", run_id)
    assert len(after) == 1
    assert after[0].created_at == initial_created_at  # not upserted


def test_history_endpoint_returns_all_versions(client: TestClient, repo: Repository) -> None:
    run_id = _complete_with_report(client, repo)
    # Manually upsert a second engine_version to simulate history.
    repo.upsert_diagnosis_report(
        "tenantA",
        run_id,
        "v0.9-test",
        "accuracy",
        5,
        5,
        [],
        ["legacy assumption"],
    )
    response = client.get(f"/api/v1/diagnostics/runs/{run_id}/history", headers=_h())
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2


def test_rediagnose_endpoint_upserts_latest(client: TestClient, repo: Repository) -> None:
    run_id = _complete_with_report(client, repo)
    initial = repo.list_diagnosis_reports("tenantA", run_id)
    assert len(initial) == 1
    initial_created_at = initial[0].created_at

    response = client.post(f"/api/v1/diagnostics/runs/{run_id}:rediagnose", headers=_h())
    assert response.status_code == 200, response.text

    after = repo.list_diagnosis_reports("tenantA", run_id)
    assert len(after) == 1  # same engine_version → updated, not duplicated
    assert after[0].created_at >= initial_created_at


def test_use_case_reports_series_was_reordered_when_db_points_out_of_order(
    client: TestClient, repo: Repository
) -> None:
    # Build a v2 report whose metric_points are insertion-order monotonic but
    # we will mutate the DB after to simulate non-monotonic insertion order.
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)
    response = _complete(
        client, job_id, runner_id, token, claim["lease_token"], _v2_report("ext-reorder")
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]

    # Reorder the val metric points so insertion order is non-monotonic.
    from sqlalchemy import select

    from store.models import MetricPointRow

    with repo.session() as s:
        rows = list(
            s.scalars(
                select(MetricPointRow).where(
                    MetricPointRow.tenant_id == "tenantA",
                    MetricPointRow.run_id == run_id,
                    MetricPointRow.series_name == "val",
                )
            ).all()
        )
        # Swap two rows' created_at to flip listing order; also swap their x_values.
        if len(rows) >= 2:
            rows.sort(key=lambda r: r.x_value)
            a, b = rows[0], rows[-1]
            # Make a appear after b in created_at order, while keeping x_values.
            from datetime import timedelta

            a.created_at = b.created_at + timedelta(seconds=1)

    # Now force a recompute via the API and ensure the reorder finding appears.
    response = client.get(
        f"/api/v1/diagnostics/runs/{run_id}",
        headers=_h(),
        params={"force_recompute": "true"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    kinds = {f["kind"] for f in data["findings"]}
    assert "series_was_reordered" in kinds
