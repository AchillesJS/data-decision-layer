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
from store.models import Base, DiagnosticSignalPointRow, JobRow, MetricPointRow, RunRow
from store.repository import Repository
from use_cases.diagnostics import get_stored_diagnosis_use_case


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


def _repo(client: TestClient) -> Repository:
    app = cast(FastAPI, client.app)
    return cast(Repository, app.dependency_overrides[get_repo]())


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


def _claim_job(
    client: TestClient,
    runner_id: str,
    runner_token: str,
    tenant: str = "tenantA",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/jobs/claim",
        headers={**_h(tenant), "X-Runner-Id": runner_id, "X-Runner-Token": runner_token},
        json={},
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def _v1_report(external: str = "direct-v1") -> dict[str, Any]:
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


def _v2_report(external: str = "direct-v2") -> dict[str, Any]:
    report = _v1_report(external)
    report["schema_version"] = 2
    report["diagnostic_signals"] = [
        {"series_name": "loss_train", "x_kind": "step", "x_value": 1, "y_value": 5.0},
        {"series_name": "loss_train", "x_kind": "step", "x_value": 2, "y_value": 3.5},
    ]
    return report


def test_runs_ingest_creates_run_and_points(client: TestClient) -> None:
    response = client.post("/api/v1/runs/ingest", headers=_h(), json=_v1_report("direct-create"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["external_run_id"] == "direct-create"
    assert body["created"] is True

    repo = _repo(client)
    with repo.read_session() as session:
        run = session.scalars(select(RunRow).where(RunRow.id == body["run_id"])).one()
        assert run.external_run_id == "direct-create"
        point_count = session.scalar(select(func.count()).select_from(MetricPointRow))
        assert point_count == 3


def test_runs_ingest_v2_creates_diagnostic_signals(client: TestClient) -> None:
    response = client.post("/api/v1/runs/ingest", headers=_h(), json=_v2_report("direct-v2-diag"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] is True

    repo = _repo(client)
    with repo.read_session() as session:
        diag_count = session.scalar(select(func.count()).select_from(DiagnosticSignalPointRow))
        assert diag_count == 2


def test_runs_ingest_idempotent_by_external_run_id(client: TestClient) -> None:
    report = _v1_report("same-direct")

    first = client.post("/api/v1/runs/ingest", headers=_h(), json=report)
    second = client.post("/api/v1/runs/ingest", headers=_h(), json=report)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["run_id"] == second.json()["run_id"]
    assert first.json()["created"] is True
    assert second.json()["created"] is False

    repo = _repo(client)
    with repo.read_session() as session:
        run_count = session.scalar(select(func.count()).select_from(RunRow))
        point_count = session.scalar(select(func.count()).select_from(MetricPointRow))
        assert run_count == 1
        assert point_count == 3


def test_runs_ingest_requires_tenant(client: TestClient) -> None:
    response = client.post("/api/v1/runs/ingest", json=_v1_report("missing-tenant"))

    assert response.status_code == 422


def test_jobs_complete_still_uses_same_ingest_logic(client: TestClient) -> None:
    report = _v1_report("shared-ingest-logic")
    direct = client.post("/api/v1/runs/ingest", headers=_h(), json=report)
    assert direct.status_code == 200, direct.text
    direct_run_id = str(direct.json()["run_id"])

    runner_id, token = _register_runner(client)
    job_id = _create_job(client)
    claim = _claim_job(client, runner_id, token)
    complete = client.post(
        f"/api/v1/jobs/{job_id}/complete",
        headers={
            **_h(),
            "X-Runner-Id": runner_id,
            "X-Runner-Token": token,
            "X-Lease-Token": str(claim["lease_token"]),
        },
        json={"status": "SUCCEEDED", "exit_code": 0, "run_report": report},
    )

    assert complete.status_code == 200, complete.text
    assert complete.json()["run_id"] == direct_run_id

    repo = _repo(client)
    with repo.read_session() as session:
        run_count = session.scalar(select(func.count()).select_from(RunRow))
        point_count = session.scalar(select(func.count()).select_from(MetricPointRow))
        job = session.scalars(select(JobRow).where(JobRow.id == job_id)).one()
        assert run_count == 1
        assert point_count == 3
        assert job.run_id == direct_run_id
def _v2_report_with_n_val_points(external: str, n: int = 10) -> dict[str, Any]:
    """Build a v2 report with n val points so the engine actually runs detectors
    (D_MIN_VAL_POINTS = 5 in diagnostics_v1)."""
    return {
        "schema_version": 2,
        "external_run_id": external,
        "run": {
            "model_tag": "m1",
            "dataset_version": "v1",
            "dataset_size": 100.0,
            "seed": 7,
            "budget_kind": "epochs",
            "budget_value": float(n),
            "metric_name": "accuracy",
            "split": "val",
            "metric_final": 0.7,
            "status": "SUCCEEDED",
            "config_hash": "abc",
            "git_commit": "def",
        },
        "metric_points": [
            {"series_name": "val", "x_kind": "epoch", "x_value": i, "y_value": 0.5 + i * 0.02}
            for i in range(1, n + 1)
        ],
        "diagnostic_signals": [],
    }


def test_runs_ingest_triggers_auto_diagnosis(client: TestClient) -> None:
    response = client.post(
        "/api/v1/runs/ingest",
        headers=_h(),
        json=_v2_report_with_n_val_points("auto-diag-1", n=10),
    )
    assert response.status_code == 200, response.text
    run_id = str(response.json()["run_id"])

    # Auto-diagnosis should have produced a stored report (best-effort, but
    # on this clean input it must succeed).
    repo = _repo(client)
    stored = get_stored_diagnosis_use_case(repo, "tenantA", run_id)
    assert stored is not None
    assert stored.run_id == run_id
    assert isinstance(stored.findings, list)


def test_runs_ingest_does_not_fail_when_diagnosis_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Patch at the source module: ingest does a lazy import and reads the name
    # at call time, so patching use_cases.diagnostics is sufficient.
    def boom(*_a: Any, **_kw: Any) -> None:
        raise RuntimeError("simulated diagnosis failure")

    monkeypatch.setattr(
        "use_cases.diagnostics.diagnose_and_store_run_use_case", boom
    )

    response = client.post(
        "/api/v1/runs/ingest",
        headers=_h(),
        json=_v2_report_with_n_val_points("auto-diag-fail", n=10),
    )
    # Ingest must still succeed; diagnosis is best-effort.
    assert response.status_code == 200, response.text
    run_id = str(response.json()["run_id"])

    # Nothing should have been stored.
    repo = _repo(client)
    stored = get_stored_diagnosis_use_case(repo, "tenantA", run_id)
    assert stored is None


def test_runs_ingest_idempotent_does_not_retrigger_diagnosis(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Spy: count how many times diagnose_and_store is invoked across re-ingests.
    import use_cases.diagnostics as diag_module

    real = diag_module.diagnose_and_store_run_use_case
    calls: list[str] = []

    def spy(repo: Any, tenant_id: str, run_id: str) -> Any:
        calls.append(run_id)
        return real(repo, tenant_id, run_id)

    monkeypatch.setattr(
        "use_cases.diagnostics.diagnose_and_store_run_use_case", spy
    )

    payload = _v2_report_with_n_val_points("idem-1", n=10)
    first = client.post("/api/v1/runs/ingest", headers=_h(), json=payload)
    second = client.post("/api/v1/runs/ingest", headers=_h(), json=payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    # Diagnosis triggered exactly once — on first ingest, skipped on idempotent re-ingest.
    assert len(calls) == 1
def test_runs_ingest_does_not_emit_series_was_reordered_for_in_order_data(
    client: TestClient,
) -> None:
    """Regression: SDK sends points in correct order; backend should not
    falsely report them as reordered after batch insert + read.
    """
    response = client.post(
        "/api/v1/runs/ingest",
        headers=_h(),
        json=_v2_report_with_n_val_points("ordered-1", n=10),
    )
    assert response.status_code == 200
    run_id = str(response.json()["run_id"])

    repo = _repo(client)
    stored = get_stored_diagnosis_use_case(repo, "tenantA", run_id)
    assert stored is not None
    finding_kinds = [f.kind for f in stored.findings]
    assert "series_was_reordered" not in finding_kinds, (
        f"False positive: in-order data triggered series_was_reordered. "
        f"All findings: {finding_kinds}"
    )
