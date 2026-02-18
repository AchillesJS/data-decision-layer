from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, joinedload, sessionmaker, with_loader_criteria

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
    hypothesis_errors,
)


def _naive_utc(dt: datetime) -> datetime:
    """Convert aware datetime to naive UTC.

    SQLite does not preserve tzinfo. We store naive UTC consistently.
    """

    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def _utcnow() -> datetime:
    """Return naive UTC datetime (SQLite-friendly)."""

    return datetime.now(UTC).replace(tzinfo=None)


_STATUS_MODEL_BY_TYPE: dict[str, type] = {
    "error": ErrorRow,
    "hypothesis": HypothesisRow,
    "action": ActionRow,
    "data_potential": DataPotentialRow,
}


_TRow = TypeVar("_TRow")


@dataclass(frozen=True)
class Repository:
    """Persistence-only repository.

    Rules:
    - store layer is dumb: no business logic, no graph integrity, no transitions.
    - use_cases orchestrate checks + writes in ONE transaction (ONE Session).

    Multi-tenant rules:
    - Every record belongs to a tenant_id.
    - Every read/write MUST be scoped by tenant_id.
    """

    engine: Engine
    SessionLocal: sessionmaker[Session]

    @classmethod
    def sqlite(cls, url: str | None = None) -> Repository:
        """Create a SQLite-backed repository.

        Resolution order for DB URL:
        1) explicit `url` argument (highest priority)
        2) env var DDW_DB_URL
        3) project default sqlite+pysqlite:///./workspace.db
        """

        resolved_url = url or os.getenv("DDW_DB_URL") or "sqlite+pysqlite:///./workspace.db"
        engine = create_engine(resolved_url, future=True)
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        return cls(engine=engine, SessionLocal=SessionLocal)

    # -----------------
    # Sessions
    # -----------------

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Write session: commit on success, rollback on error."""

        s: Session = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    @contextmanager
    def read_session(self) -> Iterator[Session]:
        """Read session: NEVER commit.

        SQLAlchemy may open an implicit transaction even for SELECTs.
        Calling rollback() on exit safely closes it.
        """

        s: Session = self.SessionLocal()
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

    def errors_exist_in_session(self, s: Session, tenant_id: str, ids: list[str]) -> bool:
        return self._ids_exist_in_session(s, ErrorRow, tenant_id, ids)

    def hypotheses_exist_in_session(self, s: Session, tenant_id: str, ids: list[str]) -> bool:
        return self._ids_exist_in_session(s, HypothesisRow, tenant_id, ids)

    def actions_exist_in_session(self, s: Session, tenant_id: str, ids: list[str]) -> bool:
        return self._ids_exist_in_session(s, ActionRow, tenant_id, ids)

    def potentials_exist_in_session(self, s: Session, tenant_id: str, ids: list[str]) -> bool:
        return self._ids_exist_in_session(s, DataPotentialRow, tenant_id, ids)

    def errors_exist(self, tenant_id: str, ids: Sequence[str]) -> bool:
        with self.read_session() as s:  # type: Session
            return self.errors_exist_in_session(s, tenant_id, list(ids))

    def hypotheses_exist(self, tenant_id: str, ids: Sequence[str]) -> bool:
        with self.read_session() as s:  # type: Session
            return self.hypotheses_exist_in_session(s, tenant_id, list(ids))

    def actions_exist(self, tenant_id: str, ids: Sequence[str]) -> bool:
        with self.read_session() as s:  # type: Session
            return self.actions_exist_in_session(s, tenant_id, list(ids))

    def potentials_exist(self, tenant_id: str, ids: Sequence[str]) -> bool:
        with self.read_session() as s:  # type: Session
            return self.potentials_exist_in_session(s, tenant_id, list(ids))

    # -----------------
    # Reads (read-only)
    # -----------------

    def get_error_in_session(self, s: Session, tenant_id: str, error_id: str) -> ErrorRow | None:
        stmt = select(ErrorRow).where(
            ErrorRow.tenant_id == tenant_id,
            ErrorRow.id == error_id,
        )
        return s.scalars(stmt).first()

    def get_error(self, tenant_id: str, error_id: str) -> ErrorRow | None:
        with self.read_session() as s:  # type: Session
            row = self.get_error_in_session(s, tenant_id, error_id)
            if row is not None:
                s.expunge(row)
            return row

    def list_errors_in_session(
        self,
        s: Session,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        y_true: str | None = None,
        y_pred: str | None = None,
    ) -> list[ErrorRow]:
        stmt = select(ErrorRow).where(ErrorRow.tenant_id == tenant_id)

        if status is not None:
            stmt = stmt.where(ErrorRow.status == status)
        if y_true is not None:
            stmt = stmt.where(ErrorRow.y_true == y_true)
        if y_pred is not None:
            stmt = stmt.where(ErrorRow.y_pred == y_pred)

        # Deterministic ordering for pagination.
        stmt = (
            stmt.order_by(ErrorRow.created_at.desc(), ErrorRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(s.scalars(stmt).all())

    def list_errors(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        y_true: str | None = None,
        y_pred: str | None = None,
    ) -> list[ErrorRow]:
        with self.read_session() as s:  # type: Session
            rows = self.list_errors_in_session(
                s,
                tenant_id,
                limit=limit,
                offset=offset,
                status=status,
                y_true=y_true,
                y_pred=y_pred,
            )
            for r in rows:
                s.expunge(r)
            return rows

    def count_errors_in_session(
        self,
        s: Session,
        tenant_id: str,
        *,
        status: str | None = None,
        y_true: str | None = None,
        y_pred: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(ErrorRow).where(ErrorRow.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(ErrorRow.status == status)
        if y_true is not None:
            stmt = stmt.where(ErrorRow.y_true == y_true)
        if y_pred is not None:
            stmt = stmt.where(ErrorRow.y_pred == y_pred)
        return int(s.execute(stmt).scalar_one())

    def count_errors(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        y_true: str | None = None,
        y_pred: str | None = None,
    ) -> int:
        with self.read_session() as s:  # type: Session
            return self.count_errors_in_session(
                s,
                tenant_id,
                status=status,
                y_true=y_true,
                y_pred=y_pred,
            )

    def get_hypothesis_in_session(
        self, s: Session, tenant_id: str, hypothesis_id: str
    ) -> HypothesisRow | None:
        stmt = (
            select(HypothesisRow)
            .where(
                HypothesisRow.tenant_id == tenant_id,
                HypothesisRow.id == hypothesis_id,
            )
            .options(
                joinedload(HypothesisRow.errors),
                with_loader_criteria(
                    ErrorRow,
                    ErrorRow.tenant_id == tenant_id,
                    include_aliases=True,
                ),
            )
        )
        return s.scalars(stmt).first()

    def get_hypothesis(self, tenant_id: str, hypothesis_id: str) -> HypothesisRow | None:
        with self.read_session() as s:  # type: Session
            row = self.get_hypothesis_in_session(s, tenant_id, hypothesis_id)
            if row is not None:
                # expunge row + loaded relationships to keep them usable after session close
                for e in row.errors:
                    s.expunge(e)
                s.expunge(row)
            return row

    def list_hypotheses_in_session(
        self,
        s: Session,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        evidence_error_id: str | None = None,
    ) -> list[HypothesisRow]:
        stmt = (
            select(HypothesisRow)
            .where(HypothesisRow.tenant_id == tenant_id)
            .options(
                joinedload(HypothesisRow.errors),
                with_loader_criteria(
                    ErrorRow,
                    ErrorRow.tenant_id == tenant_id,
                    include_aliases=True,
                ),
            )
        )

        if status is not None:
            stmt = stmt.where(HypothesisRow.status == status)

        if evidence_error_id is not None:
            stmt = (
                stmt.join(
                    hypothesis_errors,
                    hypothesis_errors.c.hypothesis_id == HypothesisRow.id,
                )
                .join(ErrorRow, ErrorRow.id == hypothesis_errors.c.error_id)
                .where(
                    ErrorRow.tenant_id == tenant_id,
                    ErrorRow.id == evidence_error_id,
                )
            )

        stmt = (
            stmt.distinct()
            .order_by(HypothesisRow.created_at.desc(), HypothesisRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(s.scalars(stmt).unique().all())

    def list_hypotheses(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        evidence_error_id: str | None = None,
    ) -> list[HypothesisRow]:
        with self.read_session() as s:  # type: Session
            rows = self.list_hypotheses_in_session(
                s,
                tenant_id,
                limit=limit,
                offset=offset,
                status=status,
                evidence_error_id=evidence_error_id,
            )
            for r in rows:
                for e in r.errors:
                    s.expunge(e)
                s.expunge(r)
            return rows

    def count_hypotheses_in_session(
        self,
        s: Session,
        tenant_id: str,
        *,
        status: str | None = None,
        evidence_error_id: str | None = None,
    ) -> int:
        stmt = (
            select(func.count(func.distinct(HypothesisRow.id)))
            .select_from(HypothesisRow)
            .where(HypothesisRow.tenant_id == tenant_id)
        )

        if status is not None:
            stmt = stmt.where(HypothesisRow.status == status)

        if evidence_error_id is not None:
            stmt = (
                stmt.join(
                    hypothesis_errors,
                    hypothesis_errors.c.hypothesis_id == HypothesisRow.id,
                )
                .join(ErrorRow, ErrorRow.id == hypothesis_errors.c.error_id)
                .where(
                    ErrorRow.tenant_id == tenant_id,
                    ErrorRow.id == evidence_error_id,
                )
            )

        return int(s.execute(stmt).scalar_one())

    def count_hypotheses(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        evidence_error_id: str | None = None,
    ) -> int:
        with self.read_session() as s:  # type: Session
            return self.count_hypotheses_in_session(
                s,
                tenant_id,
                status=status,
                evidence_error_id=evidence_error_id,
            )

    def get_action_in_session(self, s: Session, tenant_id: str, action_id: str) -> ActionRow | None:
        stmt = select(ActionRow).where(
            ActionRow.tenant_id == tenant_id,
            ActionRow.id == action_id,
        )
        return s.scalars(stmt).first()

    def get_action(self, tenant_id: str, action_id: str) -> ActionRow | None:
        with self.read_session() as s:  # type: Session
            row = self.get_action_in_session(s, tenant_id, action_id)
            if row is not None:
                s.expunge(row)
            return row

    def list_actions_in_session(
        self,
        s: Session,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        hypothesis_id: str | None = None,
    ) -> list[ActionRow]:
        stmt = select(ActionRow).where(ActionRow.tenant_id == tenant_id)

        if status is not None:
            stmt = stmt.where(ActionRow.status == status)
        if hypothesis_id is not None:
            stmt = stmt.where(ActionRow.hypothesis_id == hypothesis_id)

        stmt = (
            stmt.order_by(ActionRow.created_at.desc(), ActionRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(s.scalars(stmt).all())

    def list_actions(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        hypothesis_id: str | None = None,
    ) -> list[ActionRow]:
        with self.read_session() as s:  # type: Session
            rows = self.list_actions_in_session(
                s,
                tenant_id,
                limit=limit,
                offset=offset,
                status=status,
                hypothesis_id=hypothesis_id,
            )
            for r in rows:
                s.expunge(r)
            return rows

    def count_actions_in_session(
        self,
        s: Session,
        tenant_id: str,
        *,
        status: str | None = None,
        hypothesis_id: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(ActionRow).where(ActionRow.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(ActionRow.status == status)
        if hypothesis_id is not None:
            stmt = stmt.where(ActionRow.hypothesis_id == hypothesis_id)
        return int(s.execute(stmt).scalar_one())

    def count_actions(
        self,
        tenant_id: str,
        *,
        status: str | None = None,
        hypothesis_id: str | None = None,
    ) -> int:
        with self.read_session() as s:  # type: Session
            return self.count_actions_in_session(
                s,
                tenant_id,
                status=status,
                hypothesis_id=hypothesis_id,
            )

    def get_actions_in_session(self, s: Session, tenant_id: str, ids: list[str]) -> list[ActionRow]:
        if not ids:
            return []
        action_rows: list[ActionRow] = list(
            s.scalars(
                select(ActionRow).where(
                    ActionRow.tenant_id == tenant_id,
                    ActionRow.id.in_(list(ids)),
                )
            ).all()
        )
        return action_rows

    def get_actions(self, tenant_id: str, ids: Sequence[str]) -> list[ActionRow]:
        with self.read_session() as s:  # type: Session
            return self.get_actions_in_session(s, tenant_id, list(ids))

    def get_decision_record_in_session(
        self, s: Session, tenant_id: str, record_id: str
    ) -> DecisionRecordRow | None:
        stmt = (
            select(DecisionRecordRow)
            .where(
                DecisionRecordRow.tenant_id == tenant_id,
                DecisionRecordRow.id == record_id,
            )
            .options(
                joinedload(DecisionRecordRow.errors),
                joinedload(DecisionRecordRow.hypotheses),
                joinedload(DecisionRecordRow.actions),
                joinedload(DecisionRecordRow.potential),
                # Defensive: even if the DB contains cross-tenant links,
                # never load related rows from other tenants.
                with_loader_criteria(
                    ErrorRow,
                    ErrorRow.tenant_id == tenant_id,
                    include_aliases=True,
                ),
                with_loader_criteria(
                    HypothesisRow,
                    HypothesisRow.tenant_id == tenant_id,
                    include_aliases=True,
                ),
                with_loader_criteria(
                    ActionRow,
                    ActionRow.tenant_id == tenant_id,
                    include_aliases=True,
                ),
                with_loader_criteria(
                    DataPotentialRow,
                    DataPotentialRow.tenant_id == tenant_id,
                    include_aliases=True,
                ),
            )
        )
        return s.scalars(stmt).first()

    def get_decision_record(self, tenant_id: str, record_id: str) -> DecisionRecordRow | None:
        with self.read_session() as s:  # type: Session
            row = self.get_decision_record_in_session(s, tenant_id, record_id)
            if row is not None:
                for e in row.errors:
                    s.expunge(e)
                for h in row.hypotheses:
                    s.expunge(h)
                for a in row.actions:
                    s.expunge(a)
                if row.potential is not None:
                    s.expunge(row.potential)
                s.expunge(row)
            return row

    def list_decision_records_in_session(
        self,
        s: Session,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        decision: str | None = None,
        made_by: str | None = None,
    ) -> list[DecisionRecordRow]:
        stmt = select(DecisionRecordRow).where(DecisionRecordRow.tenant_id == tenant_id)

        if decision is not None:
            stmt = stmt.where(DecisionRecordRow.decision == decision)
        if made_by is not None:
            stmt = stmt.where(DecisionRecordRow.made_by == made_by)

        stmt = (
            stmt.options(
                joinedload(DecisionRecordRow.errors),
                joinedload(DecisionRecordRow.hypotheses),
                joinedload(DecisionRecordRow.actions),
                joinedload(DecisionRecordRow.potential),
                # Defensive: even if the DB contains cross-tenant links,
                # never load related rows from other tenants.
                with_loader_criteria(
                    ErrorRow,
                    ErrorRow.tenant_id == tenant_id,
                    include_aliases=True,
                ),
                with_loader_criteria(
                    HypothesisRow,
                    HypothesisRow.tenant_id == tenant_id,
                    include_aliases=True,
                ),
                with_loader_criteria(
                    ActionRow,
                    ActionRow.tenant_id == tenant_id,
                    include_aliases=True,
                ),
                with_loader_criteria(
                    DataPotentialRow,
                    DataPotentialRow.tenant_id == tenant_id,
                    include_aliases=True,
                ),
            )
            .order_by(DecisionRecordRow.created_at.desc(), DecisionRecordRow.id.desc())
            .limit(limit)
            .offset(offset)
        )

        # .unique() is required when using joinedload on collections.
        return list(s.scalars(stmt).unique().all())

    def list_decision_records(
        self,
        tenant_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
        decision: str | None = None,
        made_by: str | None = None,
    ) -> list[DecisionRecordRow]:
        with self.read_session() as s:  # type: Session
            rows = self.list_decision_records_in_session(
                s,
                tenant_id,
                limit=limit,
                offset=offset,
                decision=decision,
                made_by=made_by,
            )
            for row in rows:
                for e in row.errors:
                    s.expunge(e)
                for h in row.hypotheses:
                    s.expunge(h)
                for a in row.actions:
                    s.expunge(a)
                if row.potential is not None:
                    s.expunge(row.potential)
                s.expunge(row)
            return rows

    def count_decision_records_in_session(
        self,
        s: Session,
        tenant_id: str,
        *,
        decision: str | None = None,
        made_by: str | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(DecisionRecordRow)
            .where(DecisionRecordRow.tenant_id == tenant_id)
        )
        if decision is not None:
            stmt = stmt.where(DecisionRecordRow.decision == decision)
        if made_by is not None:
            stmt = stmt.where(DecisionRecordRow.made_by == made_by)
        return int(s.execute(stmt).scalar_one())

    def count_decision_records(
        self,
        tenant_id: str,
        *,
        decision: str | None = None,
        made_by: str | None = None,
    ) -> int:
        with self.read_session() as s:  # type: Session
            return self.count_decision_records_in_session(
                s,
                tenant_id,
                decision=decision,
                made_by=made_by,
            )


    # -----------------
    # Creates (write)
    # -----------------

    def create_error_in_session(self, s: Session, tenant_id: str, error: Error) -> ErrorRow:
        row = ErrorRow(
            id=str(error.id),
            tenant_id=tenant_id,
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

    def create_error(self, tenant_id: str, error: Error) -> ErrorRow:
        with self.session() as s:  # type: Session
            return self.create_error_in_session(s, tenant_id, error)

    def create_errors_in_session(
        self, s: Session, tenant_id: str, errors: list[Error]
    ) -> list[ErrorRow]:
        rows: list[ErrorRow] = [self.create_error_in_session(s, tenant_id, e) for e in errors]
        return rows

    def create_errors(self, tenant_id: str, errors: list[Error]) -> list[ErrorRow]:
        with self.session() as s:  # type: Session
            return self.create_errors_in_session(s, tenant_id, errors)

    def create_hypothesis_in_session(
        self,
        s: Session,
        tenant_id: str,
        hypothesis: Hypothesis,
        link_error_ids: list[str] | None = None,
    ) -> HypothesisRow:
        row = HypothesisRow(
            id=str(hypothesis.id),
            tenant_id=tenant_id,
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
                error_rows: list[ErrorRow] = list(
                    s.scalars(
                        select(ErrorRow).where(
                            ErrorRow.tenant_id == tenant_id,
                            ErrorRow.id.in_(list(link_error_ids)),
                        )
                    ).all()
                )
            row.errors.extend(error_rows)
        return row

    def create_hypothesis(
        self,
        tenant_id: str,
        hypothesis: Hypothesis,
        *,
        link_error_ids: list[str] | None = None,
    ) -> HypothesisRow:
        with self.session() as s:  # type: Session
            return self.create_hypothesis_in_session(
                s, tenant_id, hypothesis, link_error_ids=link_error_ids
            )

    def create_action_in_session(self, s: Session, tenant_id: str, action: Action) -> ActionRow:
        row = ActionRow(
            id=str(action.id),
            tenant_id=tenant_id,
            created_at=_naive_utc(action.created_at),
            updated_at=_naive_utc(action.updated_at),
            status=action.status.value,
            hypothesis_id=str(action.hypothesis_id) if action.hypothesis_id is not None else None,
            name=action.name,
            description=action.description,
            risk_if_false=action.risk_if_false.value,
            cost=action.cost.model_dump(),
            expected_artifacts=[str(x) for x in action.expected_artifacts],
            completed_at=(
                _naive_utc(action.completed_at) if action.completed_at is not None else None
            ),
            cancel_reason=action.cancel_reason,
        )
        s.add(row)
        return row

    def create_action(self, tenant_id: str, action: Action) -> ActionRow:
        with self.session() as s:  # type: Session
            return self.create_action_in_session(s, tenant_id, action)

    def create_data_potential_in_session(
        self, s: Session, tenant_id: str, potential: DataPotential
    ) -> DataPotentialRow:
        row = DataPotentialRow(
            id=str(potential.id),
            tenant_id=tenant_id,
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

    def create_data_potential(self, tenant_id: str, potential: DataPotential) -> DataPotentialRow:
        with self.session() as s:  # type: Session
            return self.create_data_potential_in_session(s, tenant_id, potential)

    def create_decision_record_in_session(
        self,
        s: Session,
        tenant_id: str,
        record: DecisionRecord,
        error_ids: list[str] | None,
        hypothesis_ids: list[str] | None,
        action_ids: list[str] | None,
        potential_id: str | None,
    ) -> DecisionRecordRow:
        row = DecisionRecordRow(
            id=str(record.id),
            tenant_id=tenant_id,
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
                error_rows: list[ErrorRow] = list(
                    s.scalars(
                        select(ErrorRow).where(
                            ErrorRow.tenant_id == tenant_id,
                            ErrorRow.id.in_(list(error_ids)),
                        )
                    ).all()
                )
                row.errors.extend(error_rows)
            if hypothesis_ids:
                hypothesis_rows: list[HypothesisRow] = list(
                    s.scalars(
                        select(HypothesisRow).where(
                            HypothesisRow.tenant_id == tenant_id,
                            HypothesisRow.id.in_(list(hypothesis_ids)),
                        )
                    ).all()
                )
                row.hypotheses.extend(hypothesis_rows)
            if action_ids:
                action_rows: list[ActionRow] = list(
                    s.scalars(
                        select(ActionRow).where(
                            ActionRow.tenant_id == tenant_id,
                            ActionRow.id.in_(list(action_ids)),
                        )
                    ).all()
                )
                row.actions.extend(action_rows)

        return row

    def create_decision_record(
        self,
        tenant_id: str,
        record: DecisionRecord,
        *,
        error_ids: list[str] | None = None,
        hypothesis_ids: list[str] | None = None,
        action_ids: list[str] | None = None,
        potential_id: str | None = None,
    ) -> DecisionRecordRow:
        with self.session() as s:  # type: Session
            return self.create_decision_record_in_session(
                s,
                tenant_id,
                record,
                error_ids=error_ids,
                hypothesis_ids=hypothesis_ids,
                action_ids=action_ids,
                potential_id=potential_id,
            )

    # -----------------
    # Status reads (read-only, for archive use-cases)
    # -----------------

    def get_status_in_session(
        self, s: Session, tenant_id: str, entity_type: str, entity_id: str
    ) -> str | None:
        et = entity_type.strip().lower()
        model = _STATUS_MODEL_BY_TYPE.get(et)
        if model is None:
            raise ValueError(f"Unknown entity_type: {entity_type!r}")

        # SQLAlchemy models have `.id`, `.tenant_id`, `.status` mapped attributes at runtime.
        stmt = select(model.status).where(  # type: ignore[attr-defined]
            model.tenant_id == tenant_id,  # type: ignore[attr-defined]
            model.id == entity_id,  # type: ignore[attr-defined]
        )
        status: str | None = s.scalar(stmt)
        return status

    # -----------------
    # Archive (write) - store is dumb (no transition checks)
    # -----------------

    def archive_error_in_session(self, s: Session, tenant_id: str, entity_id: str) -> None:
        row = s.scalars(
            select(ErrorRow).where(ErrorRow.tenant_id == tenant_id, ErrorRow.id == entity_id)
        ).first()
        if row is None:
            return
        row.status = "archived"
        row.updated_at = _utcnow()

    def archive_hypothesis_in_session(self, s: Session, tenant_id: str, entity_id: str) -> None:
        row = s.scalars(
            select(HypothesisRow).where(
                HypothesisRow.tenant_id == tenant_id,
                HypothesisRow.id == entity_id,
            )
        ).first()
        if row is None:
            return
        row.status = "archived"
        row.updated_at = _utcnow()

    def archive_action_in_session(self, s: Session, tenant_id: str, entity_id: str) -> None:
        row = s.scalars(
            select(ActionRow).where(ActionRow.tenant_id == tenant_id, ActionRow.id == entity_id)
        ).first()
        if row is None:
            return
        row.status = "archived"
        row.updated_at = _utcnow()

    def archive_data_potential_in_session(self, s: Session, tenant_id: str, entity_id: str) -> None:
        row = s.scalars(
            select(DataPotentialRow).where(
                DataPotentialRow.tenant_id == tenant_id,
                DataPotentialRow.id == entity_id,
            )
        ).first()
        if row is None:
            return
        row.status = "archived"
        row.updated_at = _utcnow()

    def archive_error(self, tenant_id: str, entity_id: str) -> None:
        with self.session() as s:  # type: Session
            self.archive_error_in_session(s, tenant_id, entity_id)

    def archive_hypothesis(self, tenant_id: str, entity_id: str) -> None:
        with self.session() as s:  # type: Session
            self.archive_hypothesis_in_session(s, tenant_id, entity_id)

    def archive_action(self, tenant_id: str, entity_id: str) -> None:
        with self.session() as s:  # type: Session
            self.archive_action_in_session(s, tenant_id, entity_id)

    def archive_data_potential(self, tenant_id: str, entity_id: str) -> None:
        with self.session() as s:  # type: Session
            self.archive_data_potential_in_session(s, tenant_id, entity_id)

    # -----------------
    # Internal helpers
    # -----------------

    def _ids_exist_in_session(
        self, s: Session, model: type[_TRow], tenant_id: str, ids: Sequence[str]
    ) -> bool:
        if not ids:
            return True

        unique_ids = list(set(ids))

        # SQLAlchemy models have `.id` and `.tenant_id` mapped attributes at runtime.
        id_col = model.id  # type: ignore[attr-defined]
        tenant_col = model.tenant_id  # type: ignore[attr-defined]

        found: list[str] = list(
            s.scalars(
                select(id_col).where(tenant_col == tenant_id, id_col.in_(list(unique_ids)))
            ).all()
        )
        return len(found) == len(unique_ids)
