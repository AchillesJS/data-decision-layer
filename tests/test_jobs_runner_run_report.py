from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.deps import get_repo
from api.main import create_app
from store.models import Base, MetricPointRow, RunRow
from store.repository import Repository


@pytest.fixture()
def client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    repo = Repository(
        engine=engine,
        SessionLocal=sessionmaker(bind=engine, expire_on_commit=False, future=True),
    )
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    return TestClient(app)


def _h(tenant: str = "tenantA") -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "Content-Type": "application/json"}


def _register_runner(client: TestClient, tenant: str = "tenantA") -> tuple[str, str]:
    response = client.post(
        "/api/v1/runners/register",
        headers=_h(tenant),
        json={"name": "runner-1", "tags": ["gpu", "laptop"]},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    return str(data["runner_id"]), str(data["runner_token_plain_once"])


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


def _run_report(external_run_id: str = "external-1") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "external_run_id": external_run_id,
        "run": {
            "model_tag": "m1",
            "dataset_version": "v1",
            "dataset_size": 100.0,
            "seed": 7,
            "budget_kind": "epochs",
            "budget_value": 3.0,
            "metric_name": "accuracy",
            "split": "val",
            "metric_final": 0.7,
            "status": "SUCCEEDED",
            "config_hash": "abc",
            "git_commit": "def",
        },
        "metric_points": [
            {"series_name": "val", "x_kind": "epoch", "x_value": 1, "y_value": 0.5},
            {"series_name": "val", "x_kind": "epoch", "x_value": 2, "y_value": 0.6},
            {"series_name": "val", "x_kind": "epoch", "x_value": 3, "y_value": 0.7},
        ],
    }


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


def test_complete_creates_run_and_points(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)

    response = _complete(client, job_id, runner_id, token, claim["lease_token"], _run_report())
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    assert run_id

    app = cast(FastAPI, client.app)
    repo = cast(Repository, app.dependency_overrides[get_repo]())
    with repo.read_session() as session:
        run = session.scalars(select(RunRow).where(RunRow.id == run_id)).one()
        assert run.external_run_id == "external-1"
        point_count = session.scalar(select(func.count()).select_from(MetricPointRow))
        assert point_count and point_count > 0


def test_complete_idempotent_by_external_run_id(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    report = _run_report("same-external")

    job1 = _create_job(client)
    claim1 = _claim_job(client, runner_id, token)
    r1 = _complete(client, job1, runner_id, token, claim1["lease_token"], report)
    assert r1.status_code == 200, r1.text

    job2 = _create_job(client)
    claim2 = _claim_job(client, runner_id, token)
    r2 = _complete(client, job2, runner_id, token, claim2["lease_token"], report)
    assert r2.status_code == 200, r2.text

    assert r1.json()["run_id"] == r2.json()["run_id"]
    app = cast(FastAPI, client.app)
    repo = cast(Repository, app.dependency_overrides[get_repo]())
    with repo.read_session() as session:
        run_count = session.scalar(select(func.count()).select_from(RunRow))
        assert run_count == 1


def test_metric_points_required(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)
    report = _run_report()
    report["metric_points"] = []

    response = _complete(client, job_id, runner_id, token, claim["lease_token"], report)
    assert response.status_code == 422


def test_invalid_metric_point_range(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)
    report = _run_report()
    report["metric_points"][0]["y_value"] = 1.5

    response = _complete(client, job_id, runner_id, token, claim["lease_token"], report)
    assert response.status_code == 422


def test_lease_required(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    _claim_job(client, runner_id, token)

    response = _complete(client, job_id, runner_id, token, "bad-lease", _run_report())
    assert response.status_code == 409


def test_tenant_isolation(client: TestClient) -> None:
    runner_id, token = _register_runner(client, "tenantA")
    job_id = _create_job(client, "tenantA")
    claim = _claim_job(client, runner_id, token, "tenantA")

    response = _complete(client, job_id, runner_id, token, claim["lease_token"], _run_report(), "tenantB")
    assert response.status_code in {404, 409, 422}


def test_succeeded_complete_requires_run_report(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)

    response = _complete(client, job_id, runner_id, token, claim["lease_token"], None)
    assert response.status_code == 422


def test_append_logs_duplicate_seq_returns_409(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)
    headers = {
        **_h(),
        "X-Runner-Id": runner_id,
        "X-Runner-Token": token,
        "X-Lease-Token": claim["lease_token"],
    }
    payload = {"chunks": [{"seq": 1, "stream": "stdout", "chunk": "hello"}]}

    first = client.post(f"/api/v1/jobs/{job_id}/logs:append", headers=headers, json=payload)
    assert first.status_code == 204, first.text
    second = client.post(f"/api/v1/jobs/{job_id}/logs:append", headers=headers, json=payload)
    assert second.status_code == 409, second.text


def test_log_chunk_has_size_limit(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)

    response = client.post(
        f"/api/v1/jobs/{job_id}/logs:append",
        headers={
            **_h(),
            "X-Runner-Id": runner_id,
            "X-Runner-Token": token,
            "X-Lease-Token": claim["lease_token"],
        },
        json={"chunks": [{"seq": 1, "stream": "stdout", "chunk": "x" * 64_001}]},
    )
    assert response.status_code == 422


def _runner_headers(
    runner_id: str,
    token: str,
    lease_token: str,
    tenant: str = "tenantA",
) -> dict[str, str]:
    return {
        **_h(tenant),
        "X-Runner-Id": runner_id,
        "X-Runner-Token": token,
        "X-Lease-Token": lease_token,
    }


def test_get_logs_requires_runner_and_lease_headers(client: TestClient) -> None:
    job_id = _create_job(client, "tenantA")

    response = client.get(f"/api/v1/jobs/{job_id}/logs", headers=_h("tenantA"))

    assert response.status_code == 422


def test_get_logs_rejects_invalid_runner_token(client: TestClient) -> None:
    runner_id, token = _register_runner(client, "tenantA")
    job_id = _create_job(client, "tenantA")
    claim = _claim_job(client, runner_id, token, "tenantA")

    response = client.get(
        f"/api/v1/jobs/{job_id}/logs",
        headers=_runner_headers(runner_id, "bad-token", claim["lease_token"], "tenantA"),
    )

    assert response.status_code == 409


def test_get_logs_rejects_invalid_lease_token(client: TestClient) -> None:
    runner_id, token = _register_runner(client, "tenantA")
    job_id = _create_job(client, "tenantA")
    _claim_job(client, runner_id, token, "tenantA")

    response = client.get(
        f"/api/v1/jobs/{job_id}/logs",
        headers=_runner_headers(runner_id, token, "bad-lease-token", "tenantA"),
    )

    assert response.status_code == 409


def test_get_logs_with_valid_lease_returns_chunks(client: TestClient) -> None:
    runner_id, token = _register_runner(client, "tenantA")
    job_id = _create_job(client, "tenantA")
    claim = _claim_job(client, runner_id, token, "tenantA")
    headers = _runner_headers(runner_id, token, claim["lease_token"], "tenantA")

    append_response = client.post(
        f"/api/v1/jobs/{job_id}/logs:append",
        headers=headers,
        json={"chunks": [{"seq": 1, "stream": "stdout", "chunk": "hello from runner"}]},
    )
    assert append_response.status_code == 204, append_response.text

    response = client.get(f"/api/v1/jobs/{job_id}/logs", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["seq"] == 1
    assert body[0]["stream"] == "stdout"
    assert body[0]["chunk"] == "hello from runner"


def test_get_logs_rejects_other_runner(client: TestClient) -> None:
    runner_a_id, runner_a_token = _register_runner(client, "tenantA")
    runner_b_id, runner_b_token = _register_runner(client, "tenantA")
    job_id = _create_job(client, "tenantA")
    claim = _claim_job(client, runner_a_id, runner_a_token, "tenantA")

    response = client.get(
        f"/api/v1/jobs/{job_id}/logs",
        headers=_runner_headers(runner_b_id, runner_b_token, claim["lease_token"], "tenantA"),
    )

    assert response.status_code == 409


def test_get_logs_after_complete_is_rejected(client: TestClient) -> None:
    runner_id, token = _register_runner(client, "tenantA")
    job_id = _create_job(client, "tenantA")
    claim = _claim_job(client, runner_id, token, "tenantA")
    headers = _runner_headers(runner_id, token, claim["lease_token"], "tenantA")

    complete_response = _complete(
        client,
        job_id,
        runner_id,
        token,
        claim["lease_token"],
        _run_report("run-logs-after-complete"),
        "tenantA",
    )
    assert complete_response.status_code == 200, complete_response.text

    response = client.get(f"/api/v1/jobs/{job_id}/logs", headers=headers)

    assert response.status_code == 409


def test_use_cases_jobs_does_not_import_api_schema() -> None:
    source = Path("use_cases/jobs.py").read_text(encoding="utf-8")
    assert "from api." not in source
    assert "import api." not in source


def test_store_does_not_import_api_or_use_cases() -> None:
    for path in Path("store").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert "from api." not in content
        assert "import api." not in content
        assert "from use_cases." not in content
        assert "import use_cases." not in content
