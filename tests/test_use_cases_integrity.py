from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from core.action import Action, ActionStatus, CostEstimate, RiskLevel
from core.decision import DecisionRecord, DecisionType
from core.error import Error
from core.hypothesis import Hypothesis
from store.models import ActionRow, Base, HypothesisRow
from store.repository import Repository
from use_cases.actions import UseCaseValidationError, create_action_use_case
from use_cases.archive import archive_action_use_case
from use_cases.decision_records import UseCaseIntegrityError, create_decision_record_use_case
from use_cases.hypotheses import UseCaseIntegrityError as HypothesisIntegrityError
from use_cases.hypotheses import create_hypothesis_use_case
from use_cases.transitions import ForbiddenTransitionError, ensure_transition


@pytest.fixture()
def repo() -> Repository:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return Repository(engine=engine, SessionLocal=SessionLocal)


def _seed_basic(repo: Repository):
    """Create one error + one hypothesis + one action in one txn."""
    e = Error(y_true="cat", y_pred="dog", confidence=0.7)
    h = Hypothesis(title="Lighting", statement=None)
    a = Action(
        hypothesis_id=h.id,
        name="Collect data",
        description="Collect and label more examples.",
        risk_if_false=RiskLevel.LOW,
        cost=CostEstimate(time_hours=1.0),
        status=ActionStatus.PROPOSED,
    )

    with repo.session() as s:  # type: Session
        repo.create_error_in_session(s, e)
        repo.create_hypothesis_in_session(s, h)
        repo.create_action_in_session(s, a)

    return e, h, a


def test_decision_record_rejects_missing_action_id(repo: Repository):
    e, h, _a = _seed_basic(repo)

    missing_action_id: UUID = uuid4()
    record = DecisionRecord(
        made_by="u",
        decision=DecisionType.PROCEED,
        confidence=0.6,
        rationale="We will test by collecting more data.",
        hypothesis_ids=[h.id],
        action_ids=[missing_action_id],  # pydantic parses str -> UUID
        error_ids=[e.id],
    )

    with pytest.raises(UseCaseIntegrityError):
        create_decision_record_use_case(repo, record)


def test_decision_record_rejects_action_hypothesis_mismatch(repo: Repository):
    e = Error(y_true="cat", y_pred="dog", confidence=0.7)
    h1 = Hypothesis(title="Hyp1", statement=None)
    h2 = Hypothesis(title="Hyp2", statement=None)
    a = Action(
        hypothesis_id=h2.id,
        name="Do action",
        description="Collect and label more examples.",
        risk_if_false=RiskLevel.LOW,
        cost=CostEstimate(time_hours=1.0),
        status=ActionStatus.PROPOSED,
    )
    with repo.session() as s:  # type: Session
        repo.create_error_in_session(s, e)
        repo.create_hypothesis_in_session(s, h1)
        repo.create_hypothesis_in_session(s, h2)
        repo.create_action_in_session(s, a)

    record = DecisionRecord(
        made_by="u",
        decision=DecisionType.PROCEED,
        confidence=0.6,
        rationale="We will do an action.",
        hypothesis_ids=[h1.id],  # does NOT include h2
        action_ids=[a.id],
        error_ids=[e.id],
    )
    with pytest.raises(UseCaseIntegrityError):
        create_decision_record_use_case(repo, record)


def test_forbidden_transition_rejected():
    with pytest.raises(ForbiddenTransitionError):
        ensure_transition("action", "proposed", "draft")


def test_action_non_draft_requires_hypothesis(repo: Repository):
    a = Action(
        hypothesis_id=None,
        name="Explore",
        description="Collect a small batch for exploration.",
        risk_if_false=RiskLevel.LOW,
        cost=CostEstimate(time_hours=1.0),
        status=ActionStatus.DRAFT,
    )
    # Bypass core validation by mutating (use-case must still reject).
    a.status = ActionStatus.PROPOSED
    with pytest.raises(UseCaseValidationError):
        create_action_use_case(repo, a)


def test_archive_action_use_case_sets_status_and_updated_at(repo: Repository):
    _e, _h, a = _seed_basic(repo)

    with repo.read_session() as s:  # type: Session
        row_before = s.get(ActionRow, str(a.id))
        assert row_before is not None
        before_updated = row_before.updated_at

    archive_action_use_case(repo, str(a.id))

    with repo.read_session() as s:  # type: Session
        row_after = s.get(ActionRow, str(a.id))
        assert row_after is not None
        assert row_after.status == "archived"
        assert row_after.updated_at >= before_updated


def test_archive_action_transition_allowed():
    ensure_transition("action", "proposed", "archived")


def test_hypothesis_rejects_missing_error_id(repo: Repository):
    e = Error(y_true="a", y_pred="b", confidence=0.5)
    repo.create_error(e)

    h = Hypothesis(title="Strict hypothesis", statement=None)
    missing = str(uuid4())

    with pytest.raises(HypothesisIntegrityError):
        create_hypothesis_use_case(repo, h, error_ids=[str(e.id), missing])

    with repo.read_session() as s:  # type: Session
        count = s.scalar(select(func.count()).select_from(HypothesisRow))
        assert count == 0


def test_get_decision_record_in_session_works(repo: Repository):
    e, h, a = _seed_basic(repo)

    record = DecisionRecord(
        made_by="u",
        decision=DecisionType.PROCEED,
        confidence=0.7,
        rationale="Proceed now.",
        hypothesis_ids=[h.id],
        action_ids=[a.id],
        error_ids=[e.id],
    )

    # Persist through repository (outside use-case is fine for test)
    with repo.session() as s:  # type: Session
        repo.create_decision_record_in_session(
            s,
            record,
            error_ids=[str(e.id)],
            hypothesis_ids=[str(h.id)],
            action_ids=[str(a.id)],
            potential_id=None,
        )

    with repo.read_session() as s:  # type: Session
        row = repo.get_decision_record_in_session(s, str(record.id))
        assert row is not None
        assert len(row.errors) == 1
        assert len(row.hypotheses) == 1
        assert len(row.actions) == 1


def test_read_only_session_does_not_commit(repo: Repository, monkeypatch: pytest.MonkeyPatch):
    called = {"commit": False}

    def _commit(self: Session):  # noqa: ANN001
        called["commit"] = True
        raise AssertionError("commit() should not be called in read-only sessions")

    monkeypatch.setattr(Session, "commit", _commit, raising=True)

    with repo.read_session() as s:  # type: Session
        s.execute(select(1)).all()

    assert called["commit"] is False


def test_use_case_does_not_call_wrapper_create_decision_record(repo: Repository, monkeypatch: pytest.MonkeyPatch):
    """Fail if use-case calls the non-session wrapper that opens a new session."""

    def _boom(*_args, **_kwargs):  # noqa: ANN001
        raise RuntimeError("Do not call non-session create_decision_record inside use-case")

    monkeypatch.setattr(Repository, "create_decision_record", _boom, raising=True)

    e, h, a = _seed_basic(repo)
    record = DecisionRecord(
        made_by="u",
        decision=DecisionType.PROCEED,
        confidence=0.6,
        rationale="Ok to proceed",
        hypothesis_ids=[h.id],
        action_ids=[a.id],
        error_ids=[e.id],
    )

    # Should not raise RuntimeError from wrapper
    create_decision_record_use_case(repo, record)


def test_use_case_does_not_call_wrapper_create_action(repo: Repository, monkeypatch: pytest.MonkeyPatch):
    def _boom(*_args, **_kwargs):  # noqa: ANN001
        raise RuntimeError("Do not call non-session create_action inside use-case")

    monkeypatch.setattr(Repository, "create_action", _boom, raising=True)

    h = Hypothesis(title="Hyp", statement=None)
    repo.create_hypothesis(h)

    a = Action(
        hypothesis_id=h.id,
        name="Act",
        description="Do this action.",
        risk_if_false=RiskLevel.LOW,
        cost=CostEstimate(time_hours=1.0),
        status=ActionStatus.PROPOSED,
    )

    create_action_use_case(repo, a)


def test_use_case_does_not_call_wrapper_archive_action(repo: Repository, monkeypatch: pytest.MonkeyPatch):
    def _boom(*_args, **_kwargs):  # noqa: ANN001
        raise RuntimeError("Do not call non-session archive_action inside use-case")

    monkeypatch.setattr(Repository, "archive_action", _boom, raising=True)

    _e, _h, a = _seed_basic(repo)
    archive_action_use_case(repo, str(a.id))
