from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.deps import get_repo
from api.main import create_app
from store.models import Base, DiagnosticSignalPointRow
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


def _v1_report(external: str = "ext-v1") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "external_run_id": external,
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


def _v2_report(
    external: str = "ext-v2",
    *,
    diagnostic_signals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = _v1_report(external)
    base["schema_version"] = 2
    if diagnostic_signals is not None:
        base["diagnostic_signals"] = diagnostic_signals
    return base


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


def test_v1_report_still_ingests_unchanged(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)
    response = _complete(client, job_id, runner_id, token, claim["lease_token"], _v1_report())
    assert response.status_code == 200, response.text

    app = cast(FastAPI, client.app)
    repo = cast(Repository, app.dependency_overrides[get_repo]())
    with repo.read_session() as session:
        diag_count = session.scalar(select(func.count()).select_from(DiagnosticSignalPointRow))
        assert diag_count == 0


def test_v2_report_with_diagnostic_signals_persists_them(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)

    report = _v2_report(
        external="ext-v2-1",
        diagnostic_signals=[
            {"series_name": "loss_train", "x_kind": "step", "x_value": 1, "y_value": 4.5},
            {"series_name": "loss_train", "x_kind": "step", "x_value": 2, "y_value": 3.1},
            {"series_name": "loss_train", "x_kind": "step", "x_value": 3, "y_value": 2.0},
        ],
    )
    response = _complete(client, job_id, runner_id, token, claim["lease_token"], report)
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]

    app = cast(FastAPI, client.app)
    repo = cast(Repository, app.dependency_overrides[get_repo]())
    rows = repo.list_diagnostic_signal_points_for_runs("tenantA", [run_id])
    assert len(rows) == 3
    assert {r.series_name for r in rows} == {"loss_train"}
    assert {r.x_kind for r in rows} == {"step"}
    assert sorted(r.y_value for r in rows) == [2.0, 3.1, 4.5]


def test_v2_diagnostic_signals_x_must_be_increasing(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)
    report = _v2_report(
        external="ext-v2-bad",
        diagnostic_signals=[
            {"series_name": "lr", "x_kind": "step", "x_value": 1, "y_value": 0.001},
            {"series_name": "lr", "x_kind": "step", "x_value": 1, "y_value": 0.0009},  # not increasing
        ],
    )
    response = _complete(client, job_id, runner_id, token, claim["lease_token"], report)
    assert response.status_code == 422


def test_v2_diagnostic_signals_no_y_bound(client: TestClient) -> None:
    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)
    report = _v2_report(
        external="ext-v2-unbounded",
        diagnostic_signals=[
            {"series_name": "grad_norm_global", "x_kind": "step", "x_value": 1, "y_value": -5.0},
            {"series_name": "grad_norm_global", "x_kind": "step", "x_value": 2, "y_value": 1234.5},
        ],
    )
    response = _complete(client, job_id, runner_id, token, claim["lease_token"], report)
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]

    app = cast(FastAPI, client.app)
    repo = cast(Repository, app.dependency_overrides[get_repo]())
    rows = repo.list_diagnostic_signal_points_for_runs("tenantA", [run_id])
    assert {r.y_value for r in rows} == {-5.0, 1234.5}
