from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
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


def _h(tenant: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant, "Content-Type": "application/json"}


def _run_payload(*, dataset_size: float, metric_final: float, split: str = "val") -> dict:
    return {
        "status": "SUCCEEDED",
        "dataset_version": None,
        "dataset_size": dataset_size,
        "model_tag": "m1",
        "seed": 0,
        "budget_kind": "epochs",
        "budget_value": 10,
        "metric_name": "accuracy",
        "split": split,
        "metric_final": metric_final,
        "config_hash": None,
        "git_commit": None,
    }


def _run_payload_budget(*, budget_kind: str, budget_value: float, metric_final: float, split: str = "val") -> dict:
    return {
        "status": "SUCCEEDED",
        "dataset_version": None,
        "dataset_size": 1000.0,
        "model_tag": "m1",
        "seed": 0,
        "budget_kind": budget_kind,
        "budget_value": budget_value,
        "metric_name": "accuracy",
        "split": split,
        "metric_final": metric_final,
        "config_hash": None,
        "git_commit": None,
    }


def test_create_and_list_runs_tenant_isolated(client: TestClient) -> None:
    h_a = _h("tenantA")
    h_b = _h("tenantB")

    created = client.post("/api/v1/runs", headers=h_a, json=_run_payload(dataset_size=1000, metric_final=0.50))
    assert created.status_code == 201

    listed_b = client.get("/api/v1/runs", headers=h_b)
    assert listed_b.status_code == 200
    assert listed_b.json() == []

    listed_a = client.get("/api/v1/runs", headers=h_a)
    assert listed_a.status_code == 200
    assert len(listed_a.json()) == 1


def test_analytics_insufficient_data_returns_unknown(client: TestClient) -> None:
    h_a = _h("tenantA")

    r1 = client.post(
        "/api/v1/runs",
        headers=h_a,
        json=_run_payload(dataset_size=1000, metric_final=0.50),
    )
    assert r1.status_code == 201

    r2 = client.post(
        "/api/v1/runs",
        headers=h_a,
        json=_run_payload(dataset_size=2000, metric_final=0.55),
    )
    assert r2.status_code == 201

    q = "/api/v1/analytics/learning?model_tag=m1&metric_name=accuracy&x_kind=dataset_size&split=val"
    a = client.get(q, headers=h_a)
    assert a.status_code == 200

    data = a.json()
    assert data["saturation_estimate"]["fit"]["fit_quality"] == "insufficient_data"
    assert data["regime_estimate"]["regime"] == "UNKNOWN"
    assert data["saturation_estimate"]["confidence"] < 0.4

    assert len(data["saturation_estimate"]["evidence_run_ids"]) >= 1
    assert len(data["regime_estimate"]["evidence_run_ids"]) >= 1


def test_analytics_returns_ranges_and_evidence(client: TestClient) -> None:
    h_a = _h("tenantA")

    for ds, mf in [(1000, 0.50), (2000, 0.58), (4000, 0.62)]:
        r = client.post("/api/v1/runs", headers=h_a, json=_run_payload(dataset_size=ds, metric_final=mf))
        assert r.status_code == 201

    q = "/api/v1/analytics/learning?model_tag=m1&metric_name=accuracy&x_kind=dataset_size&split=val"
    a = client.get(q, headers=h_a)
    assert a.status_code == 200

    data = a.json()
    ceiling = data["saturation_estimate"]["ceiling_range"]
    g20 = data["saturation_estimate"]["marginal_gain_p20_range"]
    g50 = data["saturation_estimate"]["marginal_gain_p50_range"]

    assert isinstance(ceiling, list)
    assert len(ceiling) == 2
    assert isinstance(g20, list)
    assert len(g20) == 2
    assert isinstance(g50, list)
    assert len(g50) == 2

    assert len(data["saturation_estimate"]["evidence_run_ids"]) >= 1


def test_analytics_no_oracle_signals_e2e(client: TestClient) -> None:
    h_a = _h("tenantA")

    for ds, mf in [(1000, 0.50), (2000, 0.58), (4000, 0.62)]:
        r = client.post(
            "/api/v1/runs",
            headers=h_a,
            json=_run_payload(dataset_size=ds, metric_final=mf),
        )
        assert r.status_code == 201

    q = "/api/v1/analytics/learning?model_tag=m1&metric_name=accuracy&x_kind=dataset_size&split=val"
    a = client.get(q, headers=h_a)
    assert a.status_code == 200
    data = a.json()

    forbidden = {"ceiling_point_estimate", "slope_gain_at_max_x_+20%"}
    names = {s["name"] for s in data["regime_estimate"]["signals"]}
    assert names.isdisjoint(forbidden)

    band = next(
        (
            s
            for s in data["regime_estimate"]["signals"]
            if s["name"] == "marginal_gain_band_+20pct"
        ),
        None,
    )
    if band is not None:
        assert isinstance(band["value"], str)
        assert band["value"] in {"LOW", "MEDIUM", "HIGH"}


def test_api_requires_tenant_header(client: TestClient) -> None:
    r = client.get("/api/v1/runs")
    assert r.status_code == 422


def test_api_requires_tenant_header_for_analytics(client: TestClient) -> None:
    q = "/api/v1/analytics/learning?model_tag=m1&metric_name=accuracy&x_kind=dataset_size&split=val"
    r = client.get(q)
    assert r.status_code == 422


def test_analytics_tenant_isolation_returns_404(client: TestClient) -> None:
    h_a = _h("tenantA")
    h_b = _h("tenantB")

    for ds, mf in [(1000, 0.50), (2000, 0.58), (4000, 0.62)]:
        r = client.post("/api/v1/runs", headers=h_a, json=_run_payload(dataset_size=ds, metric_final=mf))
        assert r.status_code == 201

    q = "/api/v1/analytics/learning?model_tag=m1&metric_name=accuracy&x_kind=dataset_size&split=val"
    r = client.get(q, headers=h_b)
    assert r.status_code == 404


def test_no_orm_leakage(client: TestClient) -> None:
    h_a = _h("tenantA")

    created = client.post("/api/v1/runs", headers=h_a, json=_run_payload(dataset_size=1234, metric_final=0.51))
    assert created.status_code == 201

    payload = created.json()
    assert "_sa_instance_state" not in payload
    assert set(payload.keys()) >= {
        "id",
        "created_at",
        "updated_at",
        "status",
        "dataset_size",
        "model_tag",
        "budget_kind",
        "budget_value",
        "metric_name",
        "metric_final",
    }


def test_invalid_run_in_db_yields_422_not_500(client: TestClient) -> None:
    h_a = _h("tenantA")
    app = cast(FastAPI, client.app)
    repo = cast(Repository, app.dependency_overrides[get_repo]())

    # Insert an invalid run bypassing API (dataset_size=0 -> dropped by engine preprocessing)
    now = datetime.now(UTC).replace(tzinfo=None)
    bad = RunRow(
        id=str(uuid4()),
        tenant_id="tenantA",
        created_at=now,
        updated_at=now,
        status="SUCCEEDED",
        dataset_version=None,
        dataset_size=0.0,
        model_tag="m1",
        seed=None,
        budget_kind="epochs",
        budget_value=10.0,
        metric_name="accuracy",
        split="val",
        metric_final=0.5,
        config_hash=None,
        git_commit=None,
    )

    with repo.session() as s:
        s.add(bad)

    q = "/api/v1/analytics/learning?model_tag=m1&metric_name=accuracy&x_kind=dataset_size&split=val"
    a = client.get(q, headers=h_a)
    assert a.status_code == 422


def test_evidence_capped_and_total_count_reported(client: TestClient) -> None:
    h_a = _h("tenantA")

    for i in range(400):
        ds = float(i + 1)
        mf = min(0.99, 0.50 + (i * 0.0005))
        r = client.post("/api/v1/runs", headers=h_a, json=_run_payload(dataset_size=ds, metric_final=mf))
        assert r.status_code == 201

    q = "/api/v1/analytics/learning?model_tag=m1&metric_name=accuracy&x_kind=dataset_size&split=val"
    a = client.get(q, headers=h_a)
    assert a.status_code == 200
    data = a.json()

    assert data["saturation_estimate"]["evidence_run_count_total"] == 400
    assert len(data["saturation_estimate"]["evidence_run_ids"]) <= 200
    assert data["regime_estimate"]["evidence_run_count_total"] == 400
    assert len(data["regime_estimate"]["evidence_run_ids"]) <= 200


def test_budget_path_uses_batch_metric_points_no_n_plus_one(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    h_a = _h("tenantA")
    app = cast(FastAPI, client.app)

    # If the old N+1 path is used, this will fail the test.
    def _boom(*args: object, **kwargs: object) -> list[MetricPointRow]:  # pragma: no cover
        raise AssertionError("N+1 list_metric_points called")

    monkeypatch.setattr(Repository, "list_metric_points", _boom)

    repo = cast(Repository, app.dependency_overrides[get_repo]())

    created_1 = client.post(
        "/api/v1/runs",
        headers=h_a,
        json=_run_payload_budget(budget_kind="steps", budget_value=100.0, metric_final=0.50),
    )
    assert created_1.status_code == 201
    run_id_1 = created_1.json()["id"]

    created_2 = client.post(
        "/api/v1/runs",
        headers=h_a,
        json=_run_payload_budget(budget_kind="steps", budget_value=200.0, metric_final=0.55),
    )
    assert created_2.status_code == 201
    run_id_2 = created_2.json()["id"]

    now = datetime.now(UTC).replace(tzinfo=None)
    with repo.session() as s:
        s.add(
            MetricPointRow(
                id=str(uuid4()),
                tenant_id="tenantA",
                run_id=run_id_1,
                series_name="val",
                x_kind="step",
                x_value=50.0,
                y_value=0.48,
                created_at=now,
            )
        )
        s.add(
            MetricPointRow(
                id=str(uuid4()),
                tenant_id="tenantA",
                run_id=run_id_2,
                series_name="val",
                x_kind="step",
                x_value=60.0,
                y_value=0.52,
                created_at=now,
            )
        )

    q = (
        "/api/v1/analytics/learning?model_tag=m1&metric_name=accuracy&x_kind=budget"
        "&split=val&budget_kind=steps"
    )
    a = client.get(q, headers=h_a)
    assert a.status_code == 200


def test_save_potential_endpoint_is_registered(client: TestClient) -> None:
    """Diagnostic: verify that POST /api/v1/analytics/save-potential exists.
    
    If this fails with 404 + body == '{"detail":"Not Found"}', the endpoint
    was not picked up by FastAPI router (import-time error suppressed).
    If it fails with 422, the endpoint is reached but body validation fails.
    """
    h_a = _h("tenantA")
    save = client.post(
        "/api/v1/analytics/save-potential",
        headers=h_a,
        json={
            "model_tag": "m1",
            "metric_name": "accuracy",
            "x_kind": "dataset_size",
        },
    )
    # We accept either 404 (NotFoundError from use_case) or 422 (validation),
    # but NOT FastAPI's default 404 with body 'Not Found'.
    if save.status_code == 404:
        body = save.json()
        # Our handler returns {"detail": "No runs found"}; FastAPI default is "Not Found".
        assert body.get("detail") == "No runs found", (
            f"Endpoint not registered. Got body: {body!r}"
        )
    else:
        # 422 also means endpoint is reached but body invalid.
        assert save.status_code in (404, 422)


def test_save_potential_from_analysis_round_trips_evidence(client: TestClient) -> None:
    h_a = _h("tenantA")
    for ds, mf in [(1000, 0.50), (2000, 0.58), (4000, 0.62), (8000, 0.64)]:
        r = client.post(
            "/api/v1/runs",
            headers=h_a,
            json=_run_payload(dataset_size=ds, metric_final=mf),
        )
        assert r.status_code == 201

    save = client.post(
        "/api/v1/analytics/save-potential",
        headers=h_a,
        json={
            "model_tag": "m1",
            "metric_name": "accuracy",
            "x_kind": "dataset_size",
            "split": "val",
        },
    )
    assert save.status_code == 201, save.text

    data = save.json()
    assert data["status"] == "estimated"
    assert data["metric_name"] == "accuracy"
    assert isinstance(data["evidence_run_ids"], list)
    assert len(data["evidence_run_ids"]) >= 1

    rng = data["upper_bound_range"]
    assert isinstance(rng, list) and len(rng) == 2
    assert 0.0 <= rng[0] <= rng[1] <= 1.0
    assert rng[1] >= data["current"]

    # No-Oracle: limiting_factors and assumptions must be present.
    assert data["limiting_factors"]
    assert data["assumptions"]


def test_save_potential_no_runs_returns_404(client: TestClient) -> None:
    h_a = _h("tenantA")
    save = client.post(
        "/api/v1/analytics/save-potential",
        headers=h_a,
        json={
            "model_tag": "m1",
            "metric_name": "accuracy",
            "x_kind": "dataset_size",
        },
    )
    assert save.status_code == 404


def test_save_potential_tenant_isolation(client: TestClient) -> None:
    h_a = _h("tenantA")
    h_b = _h("tenantB")
    for ds, mf in [(1000, 0.50), (2000, 0.58), (4000, 0.62)]:
        r = client.post(
            "/api/v1/runs",
            headers=h_a,
            json=_run_payload(dataset_size=ds, metric_final=mf),
        )
        assert r.status_code == 201

    save = client.post(
        "/api/v1/analytics/save-potential",
        headers=h_b,
        json={
            "model_tag": "m1",
            "metric_name": "accuracy",
            "x_kind": "dataset_size",
        },
    )
    assert save.status_code == 404


def test_save_potential_persists_to_potentials_endpoint(client: TestClient) -> None:
    """End-to-end: save via analytics, then read back via /potentials."""
    h_a = _h("tenantA")
    for ds, mf in [(1000, 0.50), (2000, 0.58), (4000, 0.62), (8000, 0.64)]:
        r = client.post(
            "/api/v1/runs",
            headers=h_a,
            json=_run_payload(dataset_size=ds, metric_final=mf),
        )
        assert r.status_code == 201

    save = client.post(
        "/api/v1/analytics/save-potential",
        headers=h_a,
        json={
            "model_tag": "m1",
            "metric_name": "accuracy",
            "x_kind": "dataset_size",
            "split": "val",
            "notes": "from e2e test",
        },
    )
    assert save.status_code == 201, save.text
    pot_id = save.json()["id"]

    fetched = client.get(f"/api/v1/potentials/{pot_id}", headers=h_a)
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["status"] == "estimated"
    assert body["notes"] == "from e2e test"
    assert len(body["evidence_run_ids"]) >= 1
