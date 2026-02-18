from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.action import Action, ActionStatus, CostEstimate, RiskLevel
from core.decision import DecisionRecord, DecisionType
from core.error import Error
from core.hypothesis import Hypothesis
from store.models import Base
from store.repository import Repository
from use_cases.archive import NotFoundError, archive_error_use_case
from use_cases.decision_records import UseCaseIntegrityError, create_decision_record_use_case
from use_cases.hypotheses import UseCaseIntegrityError as HypothesisIntegrityError
from use_cases.hypotheses import create_hypothesis_use_case

_TA = "tenant-a"
_TB = "tenant-b"


@pytest.fixture()
def repo() -> Repository:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return Repository(engine=engine, SessionLocal=SessionLocal)


def test_object_created_in_tenant_a_is_invisible_in_tenant_b(repo: Repository) -> None:
    e = Error(y_true="a", y_pred="b", confidence=0.5)
    repo.create_error(_TA, e)

    # repo-level isolation
    assert repo.errors_exist(_TA, [str(e.id)]) is True
    assert repo.errors_exist(_TB, [str(e.id)]) is False

    # use-case-level isolation (archive should not find it in other tenant)
    with pytest.raises(NotFoundError):
        archive_error_use_case(repo, _TB, str(e.id))


def test_cannot_create_decision_record_with_action_from_other_tenant(repo: Repository) -> None:
    # Tenant A: the record will be created here
    e_a = Error(y_true="cat", y_pred="dog", confidence=0.7)
    h_a = Hypothesis(title="Hyp A", statement=None)

    # Tenant B: action exists here only
    h_b = Hypothesis(title="Hyp B", statement=None)
    a_b = Action(
        hypothesis_id=h_b.id,
        name="Action B",
        description="Tenant B action",
        risk_if_false=RiskLevel.LOW,
        cost=CostEstimate(time_hours=1.0),
        status=ActionStatus.PROPOSED,
    )

    with repo.session() as s:  
        repo.create_error_in_session(s, _TA, e_a)
        repo.create_hypothesis_in_session(s, _TA, h_a)

        repo.create_hypothesis_in_session(s, _TB, h_b)
        repo.create_action_in_session(s, _TB, a_b)

    record = DecisionRecord(
        made_by="u",
        decision=DecisionType.PROCEED,
        confidence=0.6,
        rationale="Attempt cross-tenant",
        hypothesis_ids=[h_a.id],
        action_ids=[a_b.id],  # belongs to tenant B
        error_ids=[e_a.id],
    )

    with pytest.raises(UseCaseIntegrityError):
        create_decision_record_use_case(repo, _TA, record)


def test_cannot_link_hypothesis_to_error_across_tenants(repo: Repository) -> None:
    e_b = Error(y_true="x", y_pred="y", confidence=0.8)
    repo.create_error(_TB, e_b)

    h_a = Hypothesis(title="Hyp A", statement=None)

    with pytest.raises(HypothesisIntegrityError):
        create_hypothesis_use_case(repo, _TA, h_a, error_ids=[str(e_b.id)])
