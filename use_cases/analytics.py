from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from analytics_engine.engine_v1 import analyze_saturation
from analytics_engine.schemas import (
    DataPotentialDraft,
    RegimeEstimate,
    RunPoint,
    SaturationEstimate,
)
from core.potential import DataPotential, DataPotentialStatus
from store.models import DataPotentialRow
from store.repository import Repository
from use_cases.actions import UseCaseValidationError
from use_cases.archive import NotFoundError

_XKind = Literal["dataset_size", "budget"]


@dataclass(frozen=True)
class LearningQuery:
    model_tag: str
    metric_name: str
    x_kind: _XKind
    dataset_version: str | None = None
    split: str | None = None
    budget_kind: str | None = None


def _budget_kind_to_point_x_kind(budget_kind: str) -> str:
    mapping = {
        "steps": "step",
        "epochs": "epoch",
        "time_sec": "time",
    }
    return mapping.get(budget_kind, "")


def _best_split(query_split: str | None, run_split: str | None) -> str:
    if query_split:
        return query_split
    if run_split:
        return run_split
    return "val"


def analyze_learning_use_case(
    repo: Repository,
    tenant_id: str,
    query: LearningQuery,
) -> tuple[SaturationEstimate, RegimeEstimate, DataPotentialDraft]:
    """Analyze learning saturation from Runs (and MetricPoints when available).

    Does NOT persist DataPotential automatically.
    """

    runs = repo.list_runs(
        tenant_id,
        model_tag=query.model_tag,
        dataset_version=query.dataset_version,
        metric_name=query.metric_name,
        split=query.split,
        budget_kind=(query.budget_kind if query.x_kind == "budget" else None),
        limit=10_000,
        offset=0,
    )

    if not runs:
        raise NotFoundError("No runs found")

    run_points: list[RunPoint] = []

    if query.x_kind == "dataset_size":
        for r in runs:
            run_points.append(
                RunPoint(
                    run_id=str(r.id),
                    x_kind="dataset_size",
                    x_value=float(r.dataset_size),
                    y_value=float(r.metric_final),
                    seed=(int(r.seed) if r.seed is not None else None),
                    model_tag=str(r.model_tag),
                    dataset_version=(str(r.dataset_version) if r.dataset_version is not None else None),
                    metric_name=str(r.metric_name),
                    split=(str(r.split) if r.split is not None else None),
                    created_at=(r.created_at if isinstance(r.created_at, datetime) else None),
                )
            )
    else:
        run_ids = [str(r.id) for r in runs]
        points_all = repo.list_metric_points_for_runs(tenant_id, run_ids)

        points_by_run: dict[str, list] = {}
        for p in points_all:
            points_by_run.setdefault(str(p.run_id), []).append(p)

        for r in runs:
            run_id = str(r.id)
            desired_series = _best_split(query.split, r.split)
            desired_point_x_kind = _budget_kind_to_point_x_kind(query.budget_kind or r.budget_kind)

            points = points_by_run.get(run_id, [])
            filtered = [
                p
                for p in points
                if p.series_name == desired_series and p.x_kind == desired_point_x_kind
            ]

            if filtered:
                for p in filtered:
                    run_points.append(
                        RunPoint(
                            run_id=run_id,
                            x_kind="budget",
                            x_value=float(p.x_value),
                            y_value=float(p.y_value),
                            seed=(int(r.seed) if r.seed is not None else None),
                            model_tag=str(r.model_tag),
                            dataset_version=(
                                str(r.dataset_version) if r.dataset_version is not None else None
                            ),
                            metric_name=str(r.metric_name),
                            split=desired_series,
                            created_at=(p.created_at if isinstance(p.created_at, datetime) else None),
                        )
                    )
            else:
                run_points.append(
                    RunPoint(
                        run_id=run_id,
                        x_kind="budget",
                        x_value=float(r.budget_value),
                        y_value=float(r.metric_final),
                        seed=(int(r.seed) if r.seed is not None else None),
                        model_tag=str(r.model_tag),
                        dataset_version=(
                            str(r.dataset_version) if r.dataset_version is not None else None
                        ),
                        metric_name=str(r.metric_name),
                        split=desired_series,
                        created_at=(r.created_at if isinstance(r.created_at, datetime) else None),
                    )
                )

    try:
        sat, regime, draft = analyze_saturation(run_points)
    except ValueError as e:
        raise UseCaseValidationError(
            "Analytics engine could not analyze runs (no valid points after preprocessing).",
            errors=[str(e)],
        ) from e
    return sat, regime, draft


def save_data_potential_from_draft_use_case(
    repo: Repository,
    tenant_id: str,
    *,
    draft: DataPotentialDraft,
    metric_name: str,
    notes: str | None = None,
) -> DataPotentialRow:
    """Persist a DataPotential built from an analytics draft.

    Canon enforcement:
      - evidence_run_ids must be non-empty (No Oracle: no claim without evidence).
      - status forced to ESTIMATED; core invariants validate the rest.
      - default limiting_factors/assumptions are injected if engine returned empty,
        so we never persist an ESTIMATED potential that violates core invariants.
    """

    run_ids = [str(rid) for rid in (draft.evidence.get("run_ids") or [])]
    if not run_ids:
        raise UseCaseValidationError(
            "DataPotential requires non-empty evidence_run_ids"
        )

    sample_size = int(draft.evidence.get("run_count_total") or len(run_ids))
    if sample_size <= 0:
        sample_size = len(run_ids)

    # Core requires non-empty limiting_factors and assumptions for ESTIMATED.
    # Engine usually fills these, but defend against edge cases.
    limiting_factors = list(draft.limiting_factors) or ["unknown"]
    assumptions = list(draft.assumptions) or ["heuristic_engine_v1"]

    potential = DataPotential(
        status=DataPotentialStatus.ESTIMATED,
        metric_name=metric_name,
        current=float(draft.current),
        upper_bound_range=(float(draft.low), float(draft.high)),
        confidence=float(draft.confidence),
        sample_size=sample_size,
        limiting_factors=limiting_factors,
        assumptions=assumptions,
        evidence_run_ids=run_ids,
        notes=notes,
    )

    return repo.create_data_potential(tenant_id, potential)
