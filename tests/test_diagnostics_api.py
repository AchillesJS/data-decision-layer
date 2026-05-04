from __future__ import annotations

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


def _create_run(client: TestClient, tenant: str = "tenantA") -> str:
    payload = {
        "status": "SUCCEEDED",
        "dataset_version": "v1",
        "dataset_size": 1000.0,
        "model_tag": "m1",
        "seed": 0,
        "budget_kind": "epochs",
        "budget_value": 8.0,
        "metric_name": "accuracy",
        "split": "val",
        "metric_final": 0.7,
        "config_hash": None,
        "git_commit": None,
    }
    response = client.post("/api/v1/runs", headers=_h(tenant), json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def test_get_diagnostics_requires_tenant(client: TestClient) -> None:
    response = client.get("/api/v1/diagnostics/runs/nope")
    assert response.status_code == 422


def test_get_diagnostics_404_when_run_missing(client: TestClient) -> None:
    response = client.get("/api/v1/diagnostics/runs/does-not-exist", headers=_h())
    assert response.status_code == 404


def test_get_diagnostics_returns_report_for_existing_run(client: TestClient) -> None:
    run_id = _create_run(client)
    response = client.get(f"/api/v1/diagnostics/runs/{run_id}", headers=_h())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["run_id"] == run_id
    assert data["metric_name"] == "accuracy"
    assert isinstance(data["findings"], list)
    assert isinstance(data["assumptions"], list)


def test_diagnostics_tenant_isolation(client: TestClient) -> None:
    run_id = _create_run(client, tenant="tenantA")
    response = client.get(f"/api/v1/diagnostics/runs/{run_id}", headers=_h("tenantB"))
    assert response.status_code == 404
