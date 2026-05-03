from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from api.deps import get_repo, get_tenant_id
from api.schemas.analytics import (
    DataPotentialDraft as DataPotentialDraftRead,
)
from api.schemas.analytics import (
    LearningAnalysisRead,
    SaveFromDraftRequest,
)
from api.schemas.analytics import (
    RegimeEstimate as RegimeEstimateRead,
)
from api.schemas.analytics import (
    SaturationEstimate as SaturationEstimateRead,
)
from api.schemas.potential import DataPotentialRead
from use_cases.analytics import (
    LearningQuery,
    analyze_learning_use_case,
    save_data_potential_from_draft_use_case,
)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

TenantId = Annotated[str, Depends(get_tenant_id)]
RepoDep = Annotated[Any, Depends(get_repo)]

XKind = Literal["dataset_size", "budget"]


def _potential_row_to_read(row: Any) -> DataPotentialRead:
    return DataPotentialRead(
        id=row.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        status=row.status,
        metric_name=row.metric_name,
        current=row.current,
        upper_bound_range=row.upper_bound_range,
        scenarios=row.scenarios or {},
        confidence=row.confidence,
        sample_size=row.sample_size,
        limiting_factors=list(row.limiting_factors or []),
        assumptions=list(row.assumptions or []),
        evidence_error_ids=list(row.evidence_error_ids or []),
        evidence_run_ids=list(row.evidence_run_ids or []),
        notes=row.notes,
    )


@router.get("/learning", response_model=LearningAnalysisRead)
def analyze_learning(
    tenant_id: TenantId,
    repo: RepoDep,
    model_tag: Annotated[str, Query(min_length=1)],
    metric_name: Annotated[str, Query(min_length=1)],
    x_kind: Annotated[XKind, Query()],
    dataset_version: Annotated[str | None, Query()] = None,
    split: Annotated[str | None, Query()] = None,
    budget_kind: Annotated[str | None, Query()] = None,
) -> LearningAnalysisRead:
    q = LearningQuery(
        model_tag=model_tag,
        metric_name=metric_name,
        x_kind=x_kind,
        dataset_version=dataset_version,
        split=split,
        budget_kind=budget_kind,
    )

    sat, regime, draft = analyze_learning_use_case(repo, tenant_id, q)

    return LearningAnalysisRead(
        saturation_estimate=SaturationEstimateRead.model_validate(sat.model_dump()),
        regime_estimate=RegimeEstimateRead.model_validate(regime.model_dump()),
        potential_draft=DataPotentialDraftRead.model_validate(draft.model_dump()),
    )


@router.post(
    "/save-potential",
    response_model=DataPotentialRead,
    status_code=201,
)
def save_potential_from_analysis(
    payload: SaveFromDraftRequest,
    tenant_id: TenantId,
    repo: RepoDep,
) -> DataPotentialRead:
    """Re-runs analytics for the given query and persists the draft as DataPotential.

    Returns 201 on success, 404 if no runs match the query, 422 on validation errors.
    """

    q = LearningQuery(
        model_tag=payload.model_tag,
        metric_name=payload.metric_name,
        x_kind=payload.x_kind,
        dataset_version=payload.dataset_version,
        split=payload.split,
        budget_kind=payload.budget_kind,
    )
    _, _, draft = analyze_learning_use_case(repo, tenant_id, q)
    row = save_data_potential_from_draft_use_case(
        repo,
        tenant_id,
        draft=draft,
        metric_name=payload.metric_name,
        notes=payload.notes,
    )
    return _potential_row_to_read(row)
