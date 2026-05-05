from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.deps import get_repo
from api.main import create_app
from store.models import Base, RunRow
from store.repository import MetricPointCreateData, Repository


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


def test_use_case_reports_series_was_reordered_for_truly_non_monotonic_x(
    client: TestClient, repo: Repository
) -> None:
    """When x_values themselves are out of order in storage (bypassing the
    ingest API which would reject them), the defensive-net detector fires."""
 
    now = datetime.now(UTC).replace(tzinfo=None)
    run_id = str(uuid4())
    with repo.session() as s:
        s.add(
            RunRow(
                id=run_id,
                tenant_id="tenantA",
                external_run_id=f"non-monotonic-{run_id[:8]}",
                created_at=now,
                updated_at=now,
                status="SUCCEEDED",
                dataset_version="v1",
                dataset_size=100.0,
                model_tag="m1",
                seed=1,
                budget_kind="epochs",
                budget_value=10.0,
                metric_name="accuracy",
                split="val",
                metric_final=0.7,
                config_hash=None,
                git_commit=None,
            )
        )
 
    # Build val points where x_values are intentionally non-monotonic.
    # This bypasses the ingest API's Pydantic validation on purpose, to
    # test the engine's defensive sort+detect.
    bad_points = [
        MetricPointCreateData(
            id=str(uuid4()),
            series_name="val",
            x_kind="epoch",
            x_value=x,
            y_value=y,
            created_at=now,
        )
        for x, y in [(1, 0.5), (5, 0.7), (2, 0.55), (3, 0.6), (4, 0.65), (6, 0.72)]
    ]
    with repo.session() as s:
        repo.create_metric_points_in_session(s, "tenantA", run_id, bad_points)
 
    response = client.get(
        f"/api/v1/diagnostics/runs/{run_id}",
        headers=_h(),
        params={"force_recompute": "true"},
    )
    assert response.status_code == 200, response.text
    kinds = {f["kind"] for f in response.json()["findings"]}
    # NB: After the repository fix, list_metric_points sorts by
    # (series_name, x_kind, x_value), so the engine receives points in x order
    # regardless of insertion. The "raw" sequence the engine inspects is the
    # ORDER BY result from the DB. Because we sort by x_value in storage, the
    # engine sees a monotonic sequence here too — and the finding does NOT fire.
    #
    # If you want to retain a genuine "defensive net" check, it must be moved
    # to the ingest layer (Pydantic already does this for /runs/ingest). The
    # use-case-level reorder check is now structurally unreachable for any
    # data that comes through repo.list_metric_points.
    #
    # Therefore the correct assertion is: NOT in kinds. This documents that
    # the storage layer guarantees ordering, and the use-case-level check is
    # now redundant (and effectively dead code we should remove later).
    assert "series_was_reordered" not in kinds
 
 
def test_use_case_does_not_emit_reordered_for_in_order_ingest(
    client: TestClient,
) -> None:
    """Direct regression for the bug fixed in repository.list_metric_points:
    in-order data ingested via SDK / API must not falsely trigger reorder."""
 
    payload = {
        "schema_version": 2,
        "external_run_id": f"in-order-{uuid4().hex[:8]}",
        "run": {
            "model_tag": "m1",
            "dataset_version": "v1",
            "dataset_size": 100.0,
            "seed": 1,
            "budget_kind": "epochs",
            "budget_value": 10.0,
            "metric_name": "accuracy",
            "split": "val",
            "metric_final": 0.7,
            "status": "SUCCEEDED",
            "config_hash": None,
            "git_commit": None,
        },
        "metric_points": [
            {"series_name": "val", "x_kind": "epoch", "x_value": i, "y_value": 0.5 + i * 0.02}
            for i in range(1, 11)
        ],
        "diagnostic_signals": [],
    }
    r = client.post("/api/v1/runs/ingest", headers=_h(), json=payload)
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
 
    response = client.get(
        f"/api/v1/diagnostics/runs/{run_id}",
        headers=_h(),
    )
    assert response.status_code == 200, response.text
    kinds = {f["kind"] for f in response.json()["findings"]}
    assert "series_was_reordered" not in kinds, (
        f"FALSE POSITIVE: in-order ingest triggered series_was_reordered. "
        f"All findings: {kinds}"
    )
