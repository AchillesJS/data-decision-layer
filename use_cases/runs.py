from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from store.models import RunRow
from store.repository import Repository, RunCreateData
from use_cases.actions import UseCaseValidationError

_ALLOWED_BUDGET_KINDS = {"steps", "epochs", "time_sec"}


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def create_run_use_case(repo: Repository, tenant_id: str, payload: dict) -> RunRow:
    """Create a Run inside a tenant.

    Minimal invariants only (MVP):
      - 0 <= metric_final <= 1
      - dataset_size > 0
      - budget_value > 0
    """

    try:
        metric_final = float(payload["metric_final"])
        dataset_size = float(payload["dataset_size"])
        budget_value = float(payload["budget_value"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UseCaseValidationError("Invalid run payload") from exc

    if not (0.0 <= metric_final <= 1.0):
        raise UseCaseValidationError("metric_final must be within [0, 1]")
    if dataset_size <= 0:
        raise UseCaseValidationError("dataset_size must be > 0")
    if budget_value <= 0:
        raise UseCaseValidationError("budget_value must be > 0")

    budget_kind = str(payload.get("budget_kind") or "")
    if budget_kind not in _ALLOWED_BUDGET_KINDS:
        raise UseCaseValidationError("budget_kind must be one of: steps, epochs, time_sec")

    model_tag = str(payload.get("model_tag") or "").strip()
    metric_name = str(payload.get("metric_name") or "").strip()
    if not model_tag:
        raise UseCaseValidationError("model_tag is required")
    if not metric_name:
        raise UseCaseValidationError("metric_name is required")

    now = _utcnow_naive()
    data = RunCreateData(
        id=str(uuid4()),
        external_run_id=str(payload.get("external_run_id") or f"manual:{uuid4()}"),
        created_at=now,
        updated_at=now,
        status=str(payload.get("status") or ""),
        dataset_version=(str(payload["dataset_version"]) if payload.get("dataset_version") else None),
        dataset_size=dataset_size,
        model_tag=model_tag,
        seed=(int(payload["seed"]) if payload.get("seed") is not None else None),
        budget_kind=budget_kind,
        budget_value=budget_value,
        metric_name=metric_name,
        split=(str(payload["split"]) if payload.get("split") else None),
        metric_final=metric_final,
        config_hash=(str(payload["config_hash"]) if payload.get("config_hash") else None),
        git_commit=(str(payload["git_commit"]) if payload.get("git_commit") else None),
    )

    with repo.session() as s:
        row = repo.create_run_in_session(s, tenant_id, data)
    return row


def list_runs_use_case(
    repo: Repository,
    tenant_id: str,
    filters: dict,
    *,
    limit: int = 200,
    offset: int = 0,
) -> list[RunRow]:
    return repo.list_runs(
        tenant_id,
        model_tag=filters.get("model_tag"),
        dataset_version=filters.get("dataset_version"),
        metric_name=filters.get("metric_name"),
        split=filters.get("split"),
        budget_kind=filters.get("budget_kind"),
        limit=limit,
        offset=offset,
    )
