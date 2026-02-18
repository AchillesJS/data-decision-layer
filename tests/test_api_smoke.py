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

_TA = "tenant-a"
_TB = "tenant-b"


@pytest.fixture()
def client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    repo = Repository(engine=engine, SessionLocal=SessionLocal)

    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo

    return TestClient(app)


def test_create_error_then_get_is_tenant_scoped(client: TestClient) -> None:
    payload = {"y_true": "cat", "y_pred": "dog", "confidence": 0.7}
    r = client.post("/api/v1/errors", json=payload, headers={"X-Tenant-Id": _TA})
    assert r.status_code == 201, r.text
    data = r.json()
    error_id = data["id"]

    r = client.get(f"/api/v1/errors/{error_id}", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == error_id

    r = client.get(f"/api/v1/errors/{error_id}", headers={"X-Tenant-Id": _TB})
    assert r.status_code == 404, r.text


def test_decision_record_cross_tenant_action_is_conflict(client: TestClient) -> None:
    # Tenant B: create hypothesis + action
    r = client.post(
        "/api/v1/hypotheses",
        json={"title": "Hyp B", "statement": None},
        headers={"X-Tenant-Id": _TB},
    )
    assert r.status_code == 201, r.text
    hyp_b_id = r.json()["id"]

    r = client.post(
        "/api/v1/actions",
        json={
            "hypothesis_id": hyp_b_id,
            "name": "Action B",
            "description": "Tenant B action for API test.",
            "risk_if_false": "low",
            "cost": {"time_hours": 1.0},
            "status": "proposed",
        },
        headers={"X-Tenant-Id": _TB},
    )
    assert r.status_code == 201, r.text
    action_b_id = r.json()["id"]

    # Tenant A: create error + hypothesis
    r = client.post(
        "/api/v1/errors",
        json={"y_true": "a", "y_pred": "b", "confidence": 0.6},
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 201, r.text
    error_a_id = r.json()["id"]

    r = client.post(
        "/api/v1/hypotheses",
        json={"title": "Hyp A", "statement": None},
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 201, r.text
    hyp_a_id = r.json()["id"]

    # Attempt to create DecisionRecord in tenant A with tenant B action_id -> 409
    r = client.post(
        "/api/v1/decision-records",
        json={
            "made_by": "u",
            "decision": "proceed",
            "confidence": 0.6,
            "rationale": "Attempt cross-tenant action reference.",
            "hypothesis_ids": [hyp_a_id],
            "action_ids": [action_b_id],
            "error_ids": [error_a_id],
        },
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 409, r.text


def test_list_errors_pagination_and_filters(client: TestClient) -> None:
    # Create 5 errors for tenant A: cats/dogs + fox/wolf mix
    for i in range(1, 6):
        y_true = "cat" if i % 2 == 0 else "dog"
        y_pred = "fox" if i % 3 == 0 else "wolf"
        r = client.post(
            "/api/v1/errors",
            json={
                "y_true": y_true,
                "y_pred": y_pred,
                "confidence": 0.5 + (i * 0.01),
                "context": {"note": f"list-test-{i}"},
            },
            headers={"X-Tenant-Id": _TA},
        )
        assert r.status_code == 201, r.text

    # Tenant B should not see tenant A errors
    r = client.get("/api/v1/errors", headers={"X-Tenant-Id": _TB})
    assert r.status_code == 200, r.text
    assert r.json() == []

    # Pagination: 5 items -> pages of 2,2,1
    r0 = client.get("/api/v1/errors?limit=2&offset=0", headers={"X-Tenant-Id": _TA})
    assert r0.status_code == 200, r0.text
    p0 = r0.json()
    assert isinstance(p0, list)
    assert len(p0) == 2

    r1 = client.get("/api/v1/errors?limit=2&offset=2", headers={"X-Tenant-Id": _TA})
    assert r1.status_code == 200, r1.text
    p1 = r1.json()
    assert len(p1) == 2

    r2 = client.get("/api/v1/errors?limit=2&offset=4", headers={"X-Tenant-Id": _TA})
    assert r2.status_code == 200, r2.text
    p2 = r2.json()
    assert len(p2) == 1

    # Ensure pages do not overlap (stable ordering required)
    ids0 = {x["id"] for x in p0}
    ids1 = {x["id"] for x in p1}
    ids2 = {x["id"] for x in p2}
    assert ids0.isdisjoint(ids1)
    assert ids0.isdisjoint(ids2)
    assert ids1.isdisjoint(ids2)

    # Filters
    r = client.get("/api/v1/errors?y_true=cat", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 200, r.text
    cats = r.json()
    assert len(cats) == 2
    assert all(x["y_true"] == "cat" for x in cats)

    r = client.get("/api/v1/errors?y_pred=fox", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 200, r.text
    foxes = r.json()
    assert len(foxes) == 1
    assert all(x["y_pred"] == "fox" for x in foxes)

    r = client.get(
        "/api/v1/errors?y_true=cat&y_pred=wolf&limit=50&offset=0",
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 200, r.text
    cats_wolf = r.json()
    assert len(cats_wolf) == 2
    assert all(x["y_true"] == "cat" and x["y_pred"] == "wolf" for x in cats_wolf)


def test_list_errors_query_validation(client: TestClient) -> None:
    r = client.get("/api/v1/errors?limit=500", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 422, r.text

    r = client.get("/api/v1/errors?offset=-1", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 422, r.text


def test_list_actions_pagination_and_filters(client: TestClient) -> None:
    # Tenant A: create hypothesis for non-draft actions
    r = client.post(
        "/api/v1/hypotheses",
        json={"title": "Hyp A", "statement": None},
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 201, r.text
    hyp_id = r.json()["id"]

    # Create 5 actions for tenant A (1 draft w/o hypothesis, 4 linked)
    action_ids: list[str] = []
    for i in range(1, 6):
        payload: dict[str, object] = {
            "name": f"Action {i}",
            "description": f"Tenant A action for list test #{i}.",
            "risk_if_false": "low",
            "cost": {"time_hours": 1.0},
            "expected_artifacts": [f"artifact_{i}.txt"],
        }
        if i == 1:
            payload["status"] = "draft"
        else:
            payload["hypothesis_id"] = hyp_id
            payload["status"] = "proposed" if i in (2, 3) else "approved"

        r = client.post("/api/v1/actions", json=payload, headers={"X-Tenant-Id": _TA})
        assert r.status_code == 201, r.text
        action_ids.append(r.json()["id"])

    # Archive one action to have a distinct status value
    r = client.post(
        f"/api/v1/actions/{action_ids[2]}/archive",
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "archived"

    # Tenant B should not see tenant A actions
    r = client.get("/api/v1/actions", headers={"X-Tenant-Id": _TB})
    assert r.status_code == 200, r.text
    assert r.json() == []

    # Pagination: 5 items -> pages of 2,2,1
    r0 = client.get("/api/v1/actions?limit=2&offset=0", headers={"X-Tenant-Id": _TA})
    assert r0.status_code == 200, r0.text
    p0 = r0.json()
    assert len(p0) == 2

    r1 = client.get("/api/v1/actions?limit=2&offset=2", headers={"X-Tenant-Id": _TA})
    assert r1.status_code == 200, r1.text
    p1 = r1.json()
    assert len(p1) == 2

    r2 = client.get("/api/v1/actions?limit=2&offset=4", headers={"X-Tenant-Id": _TA})
    assert r2.status_code == 200, r2.text
    p2 = r2.json()
    assert len(p2) == 1

    ids0 = {x["id"] for x in p0}
    ids1 = {x["id"] for x in p1}
    ids2 = {x["id"] for x in p2}
    assert ids0.isdisjoint(ids1)
    assert ids0.isdisjoint(ids2)
    assert ids1.isdisjoint(ids2)

    # Filters
    r = client.get("/api/v1/actions?status=draft", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 200, r.text
    drafts = r.json()
    assert len(drafts) == 1
    assert drafts[0]["status"] == "draft"
    assert drafts[0]["hypothesis_id"] is None

    r = client.get("/api/v1/actions?status=archived", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 200, r.text
    archived = r.json()
    assert len(archived) == 1
    assert archived[0]["status"] == "archived"

    r = client.get(f"/api/v1/actions?hypothesis_id={hyp_id}", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 200, r.text
    linked = r.json()
    assert len(linked) == 4
    assert all(x["hypothesis_id"] == hyp_id for x in linked)


def test_list_decision_records_pagination_and_filters(client: TestClient) -> None:
    # Tenant A: create minimal linked entities
    r = client.post(
        "/api/v1/errors",
        json={"y_true": "cat", "y_pred": "dog", "confidence": 0.8},
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 201, r.text
    error_id = r.json()["id"]

    r = client.post(
        "/api/v1/hypotheses",
        json={"title": "Hyp for DR", "statement": None},
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 201, r.text
    hyp_id = r.json()["id"]

    r = client.post(
        "/api/v1/actions",
        json={
            "hypothesis_id": hyp_id,
            "name": "Action for DR",
            "description": "Tenant A action for decision record list test.",
            "risk_if_false": "low",
            "cost": {"time_hours": 1.0},
            "status": "proposed",
        },
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 201, r.text
    action_id = r.json()["id"]

    # Create 3 DecisionRecords (proceed, defer, reject)
    r = client.post(
        "/api/v1/decision-records",
        json={
            "made_by": "alice",
            "decision": "proceed",
            "confidence": 0.7,
            "rationale": "Proceed with an action based on current evidence.",
            "notes": "n1",
            "hypothesis_ids": [hyp_id],
            "action_ids": [action_id],
            "error_ids": [],
        },
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 201, r.text
    dr1 = r.json()["id"]

    r = client.post(
        "/api/v1/decision-records",
        json={
            "made_by": "bob",
            "decision": "defer",
            "confidence": 0.6,
            "rationale": "Need more evidence before committing to actions.",
            "notes": "n2",
            "hypothesis_ids": [hyp_id],
            "action_ids": [],
            "error_ids": [],
        },
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 201, r.text
    dr2 = r.json()["id"]

    r = client.post(
        "/api/v1/decision-records",
        json={
            "made_by": "alice",
            "decision": "reject",
            "confidence": 0.55,
            "rationale": "Reject actions for now; the evidence is not convincing.",
            "notes": "n3",
            "hypothesis_ids": [],
            "action_ids": [],
            "error_ids": [error_id],
        },
        headers={"X-Tenant-Id": _TA},
    )
    assert r.status_code == 201, r.text
    dr3 = r.json()["id"]

    # Tenant B should not see tenant A decision records
    r = client.get("/api/v1/decision-records", headers={"X-Tenant-Id": _TB})
    assert r.status_code == 200, r.text
    assert r.json() == []

    # Pagination: 3 items -> pages of 2,1
    r0 = client.get(
        "/api/v1/decision-records?limit=2&offset=0", headers={"X-Tenant-Id": _TA}
    )
    assert r0.status_code == 200, r0.text
    p0 = r0.json()
    assert len(p0) == 2

    r1 = client.get(
        "/api/v1/decision-records?limit=2&offset=2", headers={"X-Tenant-Id": _TA}
    )
    assert r1.status_code == 200, r1.text
    p1 = r1.json()
    assert len(p1) == 1

    ids0 = {x["id"] for x in p0}
    ids1 = {x["id"] for x in p1}
    assert ids0.isdisjoint(ids1)

    # Filter by decision
    r = client.get(
        "/api/v1/decision-records?decision=defer", headers={"X-Tenant-Id": _TA}
    )
    assert r.status_code == 200, r.text
    defer = r.json()
    assert len(defer) == 1
    assert defer[0]["id"] == dr2
    assert defer[0]["decision"] == "defer"

    # Filter by made_by
    r = client.get(
        "/api/v1/decision-records?made_by=alice", headers={"X-Tenant-Id": _TA}
    )
    assert r.status_code == 200, r.text
    alice = r.json()
    assert {x["id"] for x in alice} == {dr1, dr3}


def test_list_actions_and_decision_records_query_validation(client: TestClient) -> None:
    r = client.get("/api/v1/actions?limit=500", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 422, r.text

    r = client.get("/api/v1/actions?offset=-1", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 422, r.text

    r = client.get("/api/v1/decision-records?limit=500", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 422, r.text

    r = client.get("/api/v1/decision-records?offset=-1", headers={"X-Tenant-Id": _TA})
    assert r.status_code == 422, r.text
