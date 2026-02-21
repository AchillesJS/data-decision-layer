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
    repo = Repository(engine=engine, SessionLocal=sessionmaker(bind=engine, expire_on_commit=False, future=True))

    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    return TestClient(app)


def _h(tenant: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "Content-Type": "application/json"}


def test_tenant_required_everywhere_except_health(client: TestClient) -> None:
    assert client.get("/health").status_code == 200

    assert client.get("/api/v1/hypotheses").status_code == 422
    assert client.get("/api/v1/actions").status_code == 422
    assert client.get("/api/v1/decision-records").status_code == 422
    assert client.get("/api/v1/potentials").status_code == 422


def test_no_429_anywhere(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DDW_RATE_LIMIT_RPM", "1")
    headers = _h("tenantA")

    for _ in range(5):
        r = client.get("/api/v1/hypotheses", headers=headers)
        assert r.status_code != 429


def test_hypothesis_list_and_filters(client: TestClient) -> None:
    h = _h("tenantA")

    err = client.post(
        "/api/v1/errors",
        headers=h,
        json={
            "y_true": "cat",
            "y_pred": "dog",
            "confidence": 0.9,
            "uncertainty": 0.2,
            "repeatability": 1,
            "context": {"split": "val"},
        },
    )
    assert err.status_code == 201
    err_id = err.json()["id"]

    r1 = client.post("/api/v1/hypotheses", headers=h, json={"title": "H-draft"})
    assert r1.status_code == 201

    r2 = client.post(
        "/api/v1/hypotheses",
        headers=h,
        json={
            "title": "H-active",
            "status": "active",
            "statement": "This is a test statement.",
            "evidence_error_ids": [err_id],
        },
    )
    assert r2.status_code == 201

    rl = client.get("/api/v1/hypotheses", headers=h)
    assert rl.status_code == 200
    assert rl.headers.get("X-Total-Count") == "2"

    rd = client.get("/api/v1/hypotheses?status=draft", headers=h)
    assert rd.status_code == 200
    assert rd.headers.get("X-Total-Count") == "1"
    assert len(rd.json()) == 1

    re = client.get(f"/api/v1/hypotheses?evidence_error_id={err_id}", headers=h)
    assert re.status_code == 200
    assert re.headers.get("X-Total-Count") == "1"
    assert len(re.json()) == 1


def test_transition_forbidden_returns_409(client: TestClient) -> None:
    h = _h("tenantA")

    err = client.post(
        "/api/v1/errors",
        headers=h,
        json={
            "y_true": "a",
            "y_pred": "b",
            "confidence": 0.8,
            "uncertainty": 0.2,
            "repeatability": 1,
            "context": {},
        },
    )
    assert err.status_code == 201
    err_id = err.json()["id"]

    hyp = client.post(
        "/api/v1/hypotheses",
        headers=h,
        json={
            "title": "Hypothesis Active",
            "status": "active",
            "statement": "This is a test statement.",
            "evidence_error_ids": [err_id],
        },
    )
    assert hyp.status_code == 201
    hid = hyp.json()["id"]

    tr = client.post(
        f"/api/v1/hypotheses/{hid}/transition",
        headers=h,
        json={"to_status": "supported"},
    )
    assert tr.status_code == 409


def test_potentials_crud_minimum(client: TestClient) -> None:
    h = _h("tenantA")

    created = client.post(
        "/api/v1/potentials",
        headers=h,
        json={
            "metric_name": "accuracy",
            "current": 0.5,
            "confidence": 0.7,
            "sample_size": 100,
        },
    )
    assert created.status_code == 201
    pid = created.json()["id"]

    got = client.get(f"/api/v1/potentials/{pid}", headers=h)
    assert got.status_code == 200
    assert got.json()["id"] == pid

    listed = client.get("/api/v1/potentials", headers=h)
    assert listed.status_code == 200
    assert listed.headers.get("X-Total-Count") == "1"
    assert len(listed.json()) == 1

    archived = client.post(f"/api/v1/potentials/{pid}/archive", headers=h)
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
