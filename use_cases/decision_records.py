from __future__ import annotations

from core.decision import DecisionRecord
from store.repository import Repository


class UseCaseIntegrityError(ValueError):
    """Raised when referential or cross-reference rules are violated."""


def create_decision_record_use_case(repo: Repository, record: DecisionRecord) -> None:
    """Create a DecisionRecord with integrity checks in ONE transaction.

    Enforce:
      (R1) All referenced IDs must exist.
      (R2) For each action_id:
           if Action.hypothesis_id is not None,
           it must be included in provided hypothesis_ids.

    IMPORTANT:
      - All checks + write run in a single write Session (TOCTOU closed).
      - Use-cases must call *_in_session methods only while inside repo.session().
    """
    error_ids = [str(x) for x in record.error_ids]
    hypothesis_ids = [str(x) for x in record.hypothesis_ids]
    action_ids = [str(x) for x in record.action_ids]
    potential_id = str(record.potential_id) if record.potential_id is not None else None

    with repo.session() as s:
        # (R1) existence checks
        if not repo.errors_exist_in_session(s, error_ids):
            raise UseCaseIntegrityError("DecisionRecord references missing error_id")
        if not repo.hypotheses_exist_in_session(s, hypothesis_ids):
            raise UseCaseIntegrityError("DecisionRecord references missing hypothesis_id")
        if not repo.actions_exist_in_session(s, action_ids):
            raise UseCaseIntegrityError("DecisionRecord references missing action_id")
        if potential_id is not None and not repo.potentials_exist_in_session(s, [potential_id]):
            raise UseCaseIntegrityError("DecisionRecord references missing potential_id")

        # (R2) action -> hypothesis consistency
        actions = repo.get_actions_in_session(s, action_ids)
        hset = set(hypothesis_ids)
        for a in actions:
            if a.hypothesis_id is not None and a.hypothesis_id not in hset:
                raise UseCaseIntegrityError(
                    "Action.hypothesis_id must be included in DecisionRecord.hypothesis_ids"
                )

        repo.create_decision_record_in_session(
            s,
            record,
            error_ids=error_ids,
            hypothesis_ids=hypothesis_ids,
            action_ids=action_ids,
            potential_id=potential_id,
        )
