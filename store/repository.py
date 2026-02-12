from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from core.action import Action
from core.decision import DecisionRecord
from core.error import Error
from core.hypothesis import Hypothesis
from core.potential import DataPotential
from store.models import (
    ActionRow,
    DataPotentialRow,
    DecisionRecordRow,
    ErrorRow,
    HypothesisRow,
)


def _naive_utc(dt: datetime) -> datetime:
    """Convert aware datetime to naive UTC.

    SQLite does not preserve tzinfo. We store naive UTC consistently.
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def _utcnow() -> datetime:
    # Requirement: timestamps created as naive UTC.
    return datetime.utcnow()


_STATUS_MODEL_BY_TYPE: dict[str, type] = {
    "error": ErrorRow,
    "hypothesis": HypothesisRow,
    "action": ActionRow,
    "data_potential": DataPotentialRow,
}


@dataclass(frozen=True)
class Repository:
    """Persistence-only repository.

    Rules:
    - store layer is dumb: no business logic, no graph integrity, no transitions.
    - use_cases orchestrate checks + writes in ONE transaction (ONE Session).
    """

    engine: Engine
    SessionLocal: sessionmaker[Session]

    @classmethod
    def sqlite(cls, url: str = "sqlite+pysqlite:///./workspace.db") -> Repository:
        engine = create_engine(url, future=True)
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        return cls(engine=engine, SessionLocal=SessionLocal)

    # -----------------
    # Sessions
    # -----------------

    @contextmanager
    def session(self) -> Iterable[Session]:
        """Write session: commit on success, rollback on error."""
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    @contextmanager
    def read_session(self) -> Iterable[Session]:
        """Read session: NEVER commit.

        SQLAlchemy may open an implicit transaction even for SELECTs.
        Calling rollback() on exit safely closes it.
        """
        s = self.SessionLocal()
        try:
            yield s
            s.rollback()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # -----------------
    # Existence checks (read-only)
    # -----------------

    def errors_exist_in_session(self, s: Session, ids: list[str]) -> bool:
        return self._ids_exist_in_session(s, ErrorRow, ids)

    def hypotheses_exist_in_session(self, s: Session, ids: list[str]) -> bool:
        return self._ids_exist_in_session(s, HypothesisRow, ids)

    def actions_exist_in_session(self, s: Session, ids: list[str]) -> bool:
        return self._ids_exist_in_session(s, ActionRow, ids)

    def potentials_exist_in_session(self, s: Session, ids: list[str]) -> bool:
        return self._ids_exist_in_session(s, DataPotentialRow, ids)

    def errors_exist(self, ids: Sequence[str]) -> bool:
        with self.read_session() as s:
            return self.errors_exist_in_session(s, list(ids))

    def hypotheses_exist(self, ids: Sequence[str]) -> bool:
        with self.read_session() as s:
            return self.hypotheses_exist_in_session(s, list(ids))

    def actions_exist(self, ids: Sequence[str]) -> bool:
        with self.read_session() as s:
            return self.actions_exist_in_session(s, list(ids))

    def potentials_exist(self, ids: Sequence[str]) -> bool:
        with self.read_session() as s:
            return self.potentials_exist_in_session(s, list(ids))

    # -----------------
    # Reads (read-only)
    # -----------------

    def get_actions_in_session(self, s: Session, ids: list[str]) -> list[ActionRow]:
        if not ids:
            return []
        return s.scalars(select(ActionRow).where(ActionRow.id.in_(list(ids)))).all()

    def get_actions(self, ids: Sequence[str]) -> list[ActionRow]:
        with self.read_session() as s:
            return self.get_actions_in_session(s, list(ids))

    def get_decision_record_in_session(
        self, s: Session, record_id: str
    ) -> DecisionRecordRow | None:
        stmt = (
            select(DecisionRecordRow)
            .where(DecisionRecordRow.id == record_id)
            .options(
                joinedload(DecisionRecordRow.errors),
                joinedload(DecisionRecordRow.hypotheses),
                joinedload(DecisionRecordRow.actions),
                joinedload(DecisionRecordRow.potential),
            )
        )
        return s.scalars(stmt).first()

    def get_decision_record(self, record_id: str) -> DecisionRecordRow | None:
        with self.read_session() as s:
            return self.get_decision_record_in_session(s, record_id)

    # -----------------
    # Creates (write)
    # -----------------

    def create_error_in_session(self, s: Session, error: Error) -> ErrorRow:
        row = ErrorRow(
            id=str(error.id),
            created_at=_naive_utc(error.created_at),
            updated_at=_naive_utc(error.updated_at),
            status=error.status.value,
            y_true=error.y_true,
            y_pred=error.y_pred,
            confidence=error.confidence,
            uncertainty=error.uncertainty,
            repeatability=error.repeatability,
            example_ref=error.example_ref,
            context=error.context,
        )
        s.add(row)
        return row

    def create_error(self, error: Error) -> ErrorRow:
        with self.session() as s:
            return self.create_error_in_session(s, error)

    def create_errors_in_session(self, s: Session, errors: list[Error]) -> list[ErrorRow]:
        rows = [self.create_error_in_session(s, e) for e in errors]
        return rows

    def create_errors(self, errors: list[Error]) -> list[ErrorRow]:
        with self.session() as s:
            return self.create_errors_in_session(s, errors)

    def create_hypothesis_in_session(
        self,
        s: Session,
        hypothesis: Hypothesis,
        link_error_ids: list[str] | None = None,
    ) -> HypothesisRow:
        row = HypothesisRow(
            id=str(hypothesis.id),
            created_at=_naive_utc(hypothesis.created_at),
            updated_at=_naive_utc(hypothesis.updated_at),
            status=hypothesis.status.value,
            title=hypothesis.title,
            statement=hypothesis.statement,
            arguments=[str(x) for x in hypothesis.arguments],
            alternatives=[str(x) for x in hypothesis.alternatives],
            uncertainty=hypothesis.uncertainty,
            scope=hypothesis.scope.model_dump() if hypothesis.scope is not None else None,
            tags=[str(x) for x in hypothesis.tags],
        )
        s.add(row)
        if link_error_ids:
            # Ensure row is in session before wiring relationships.
            with s.no_autoflush:
                errors = s.scalars(select(ErrorRow).where(ErrorRow.id.in_(list(link_error_ids)))).all()
            row.errors.extend(errors)
        return row

    def create_hypothesis(
        self,
        hypothesis: Hypothesis,
        *,
        link_error_ids: list[str] | None = None,
    ) -> HypothesisRow:
        with self.session() as s:
            return self.create_hypothesis_in_session(s, hypothesis, link_error_ids=link_error_ids)

    def create_action_in_session(self, s: Session, action: Action) -> ActionRow:
        row = ActionRow(
            id=str(action.id),
            created_at=_naive_utc(action.created_at),
            updated_at=_naive_utc(action.updated_at),
            status=action.status.value,
            hypothesis_id=str(action.hypothesis_id) if action.hypothesis_id is not None else None,
            name=action.name,
            description=action.description,
            risk_if_false=action.risk_if_false.value,
            cost=action.cost.model_dump(),
            expected_artifacts=[str(x) for x in action.expected_artifacts],
            completed_at=_naive_utc(action.completed_at) if action.completed_at is not None else None,
            cancel_reason=action.cancel_reason,
        )
        s.add(row)
        return row

    def create_action(self, action: Action) -> ActionRow:
        with self.session() as s:
            return self.create_action_in_session(s, action)

    def create_data_potential_in_session(self, s: Session, potential: DataPotential) -> DataPotentialRow:
        row = DataPotentialRow(
            id=str(potential.id),
            created_at=_naive_utc(potential.created_at),
            updated_at=_naive_utc(potential.updated_at),
            status=potential.status.value,
            metric_name=potential.metric_name,
            current=potential.current,
            upper_bound_range=list(potential.upper_bound_range)
            if potential.upper_bound_range is not None
            else None,
            scenarios={k: list(v) for k, v in (potential.scenarios or {}).items()}
            if potential.scenarios is not None
            else None,
            confidence=potential.confidence,
            sample_size=potential.sample_size,
            limiting_factors=[str(x) for x in potential.limiting_factors],
            assumptions=[str(x) for x in potential.assumptions],
            evidence_error_ids=[str(x) for x in potential.evidence_error_ids],
            notes=potential.notes,
        )
        s.add(row)
        return row

    def create_data_potential(self, potential: DataPotential) -> DataPotentialRow:
        with self.session() as s:
            return self.create_data_potential_in_session(s, potential)

    def create_decision_record_in_session(
        self,
        s: Session,
        record: DecisionRecord,
        error_ids: list[str] | None,
        hypothesis_ids: list[str] | None,
        action_ids: list[str] | None,
        potential_id: str | None,
    ) -> DecisionRecordRow:
        row = DecisionRecordRow(
            id=str(record.id),
            created_at=_naive_utc(record.created_at),
            made_by=record.made_by,
            decision=record.decision.value,
            confidence=record.confidence,
            rationale=record.rationale,
            notes=record.notes,
            potential_id=potential_id,
        )

        s.add(row)
        with s.no_autoflush:
            if error_ids:
                rows = s.scalars(select(ErrorRow).where(ErrorRow.id.in_(list(error_ids)))).all()
                row.errors.extend(rows)
            if hypothesis_ids:
                rows = s.scalars(
                    select(HypothesisRow).where(HypothesisRow.id.in_(list(hypothesis_ids)))
                ).all()
                row.hypotheses.extend(rows)
            if action_ids:
                rows = s.scalars(select(ActionRow).where(ActionRow.id.in_(list(action_ids)))).all()
                row.actions.extend(rows)

        return row

    def create_decision_record(
        self,
        record: DecisionRecord,
        *,
        error_ids: list[str] | None = None,
        hypothesis_ids: list[str] | None = None,
        action_ids: list[str] | None = None,
        potential_id: str | None = None,
    ) -> DecisionRecordRow:
        with self.session() as s:
            return self.create_decision_record_in_session(
                s,
                record,
                error_ids=error_ids,
                hypothesis_ids=hypothesis_ids,
                action_ids=action_ids,
                potential_id=potential_id,
            )

    # -----------------
    # Status reads (read-only, for archive use-cases)
    # -----------------

    def get_status_in_session(self, s: Session, entity_type: str, entity_id: str) -> str | None:
        et = entity_type.strip().lower()
        model = _STATUS_MODEL_BY_TYPE.get(et)
        if model is None:
            raise ValueError(f"Unknown entity_type: {entity_type!r}")
        row = s.get(model, entity_id)
        return None if row is None else row.status

    # -----------------
    # Archive (write) - store is dumb (no transition checks)
    # -----------------

    def archive_error_in_session(self, s: Session, entity_id: str) -> None:
        row = s.get(ErrorRow, entity_id)
        if row is None:
            return
        row.status = "archived"
        row.updated_at = _utcnow()

    def archive_hypothesis_in_session(self, s: Session, entity_id: str) -> None:
        row = s.get(HypothesisRow, entity_id)
        if row is None:
            return
        row.status = "archived"
        row.updated_at = _utcnow()

    def archive_action_in_session(self, s: Session, entity_id: str) -> None:
        row = s.get(ActionRow, entity_id)
        if row is None:
            return
        row.status = "archived"
        row.updated_at = _utcnow()

    def archive_data_potential_in_session(self, s: Session, entity_id: str) -> None:
        row = s.get(DataPotentialRow, entity_id)
        if row is None:
            return
        row.status = "archived"
        row.updated_at = _utcnow()

    def archive_error(self, entity_id: str) -> None:
        with self.session() as s:
            self.archive_error_in_session(s, entity_id)

    def archive_hypothesis(self, entity_id: str) -> None:
        with self.session() as s:
            self.archive_hypothesis_in_session(s, entity_id)

    def archive_action(self, entity_id: str) -> None:
        with self.session() as s:
            self.archive_action_in_session(s, entity_id)

    def archive_data_potential(self, entity_id: str) -> None:
        with self.session() as s:
            self.archive_data_potential_in_session(s, entity_id)

    # -----------------
    # Internal helpers
    # -----------------

    def _ids_exist_in_session(self, s: Session, model: type, ids: Sequence[str]) -> bool:
        if not ids:
            return True
        found = s.scalars(select(model.id).where(model.id.in_(list(ids)))).all()  # type: ignore[attr-defined]
        return len(found) == len(set(ids))
