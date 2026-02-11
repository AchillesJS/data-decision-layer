import pytest
from pydantic import ValidationError

from core.action import Action, ActionStatus, CostEstimate, RiskLevel
from core.decision import DecisionRecord, DecisionType
from core.error import Error, ErrorStatus
from core.hypothesis import ErrorScope, Hypothesis, HypothesisStatus
from core.potential import DataPotential, DataPotentialStatus


def test_error_ok():
    e = Error(y_true="cat", y_pred="dog", confidence=0.7)
    assert e.confidence == 0.7
    assert e.status == ErrorStatus.OBSERVED


def test_error_requires_mismatch():
    with pytest.raises(ValidationError):
        Error(y_true="cat", y_pred="cat", confidence=0.7)


def test_hypothesis_draft_can_be_minimal():
    h = Hypothesis(title="Low lighting", statement=None)
    assert h.status == HypothesisStatus.DRAFT


def test_hypothesis_non_draft_requires_grounding():
    with pytest.raises(ValidationError):
        Hypothesis(title="T", statement="This is a sufficiently long statement.", status=HypothesisStatus.ACTIVE)

    h = Hypothesis(
        title="Hands are occluded",
        statement="If hands are occluded, the model confuses signs.",
        status=HypothesisStatus.ACTIVE,
        scope=ErrorScope(filters={"scene": "occluded"}, min_count=5),
    )
    assert h.scope is not None


def test_action_requires_cost_and_hypothesis_link():
    h = Hypothesis(title="Low lighting", statement=None)
    a = Action(
        hypothesis_id=h.id,
        name="Collect low-light data",
        description="Collect and label additional low-light examples for ambiguous signs.",
        risk_if_false=RiskLevel.MEDIUM,
        cost=CostEstimate(time_hours=8.0),
        expected_artifacts=["new_labels"],
    )
    assert a.hypothesis_id == h.id

    with pytest.raises(ValidationError):
        CostEstimate()  # must set at least one dimension


def test_action_done_requires_completed_at():
    h = Hypothesis(title="Camera angle", statement=None)

    with pytest.raises(ValidationError):
        Action(
            hypothesis_id=h.id,
            name="Fix angle in capture",
            description="Update capture guide to require full hand visibility.",
            risk_if_false=RiskLevel.LOW,
            cost=CostEstimate(time_hours=1.0),
            status=ActionStatus.DONE,
        )


def test_action_draft_can_omit_hypothesis():
    a = Action(
        hypothesis_id=None,
        name="Explore error slice",
        description="Collect a small batch of examples to see if a suspected slice exists.",
        risk_if_false=RiskLevel.LOW,
        cost=CostEstimate(time_hours=0.5),
        status=ActionStatus.DRAFT,
    )
    assert a.hypothesis_id is None

    with pytest.raises(ValidationError):
        Action(
            hypothesis_id=None,
            name="Non-draft action without hypothesis",
            description="This should be rejected because it is not DRAFT.",
            risk_if_false=RiskLevel.LOW,
            cost=CostEstimate(time_hours=1.0),
            status=ActionStatus.PROPOSED,
        )


def test_decision_record_invariants():
    h = Hypothesis(
        title="Class ambiguity",
        statement="Some classes are visually ambiguous, causing systematic confusion.",
        status=HypothesisStatus.ACTIVE,
        arguments=["Confusions are consistent across runs."],
    )
    a = Action(
        hypothesis_id=h.id,
        name="Add disambiguating labels",
        description="Add finer-grained labels or metadata to separate ambiguous cases.",
        risk_if_false=RiskLevel.HIGH,
        cost=CostEstimate(time_hours=12.0),
    )

    d = DecisionRecord(
        made_by="user",
        decision=DecisionType.PROCEED,
        confidence=0.55,
        rationale="Repeated confusions; we will test by collecting more disambiguating data.",
        hypothesis_ids=[h.id],
        action_ids=[a.id],
    )
    assert d.decision == DecisionType.PROCEED

    with pytest.raises(ValidationError):
        DecisionRecord(
            made_by="user",
            decision=DecisionType.PROCEED,
            confidence=0.5,
            rationale="Proceed but no actions.",
            hypothesis_ids=[h.id],
        )

    with pytest.raises(ValidationError):
        DecisionRecord(
            made_by="user",
            decision=DecisionType.REJECT,
            confidence=0.5,
            rationale="Reject but action referenced.",
            action_ids=[a.id],
        )


def test_data_potential_invariants():
    # Range must be within 0..1 and have high >= current.
    with pytest.raises(ValidationError):
        DataPotential(
            metric_name="accuracy",
            current=0.7,
            upper_bound_range=(0.8, 0.65),  # low > high
        )

    with pytest.raises(ValidationError):
        DataPotential(
            metric_name="accuracy",
            current=0.7,
            upper_bound_range=(0.6, 0.69),  # high < current
        )

    # ESTIMATED requires range, limiting_factors, assumptions, and sample_size>0.
    with pytest.raises(ValidationError):
        DataPotential(
            metric_name="accuracy",
            current=0.7,
            status=DataPotentialStatus.ESTIMATED,
            upper_bound_range=(0.65, 0.85),
            limiting_factors=["label noise"],
            assumptions=["labeling policy unchanged"],
            sample_size=0,
        )

    p = DataPotential(
        metric_name="accuracy",
        current=0.7,
        status=DataPotentialStatus.ESTIMATED,
        upper_bound_range=(0.65, 0.85),  # low may be < current (noise/drift happens)
        limiting_factors=["label noise", "coverage gaps"],
        assumptions=["labeling policy unchanged", "same deployment distribution"],
        scenarios={"best_case": (0.75, 0.9)},
        sample_size=500,
    )
    assert p.upper_bound_range == (0.65, 0.85)
