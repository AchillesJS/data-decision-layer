from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from store.models import RunnerRow
from store.repository import Repository, RunnerCreateData
from use_cases.actions import UseCaseValidationError
from use_cases.archive import NotFoundError


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def verify_secret(secret: str, secret_hash: str) -> bool:
    return secrets.compare_digest(hash_secret(secret), secret_hash)


@dataclass(frozen=True)
class RegisteredRunner:
    runner_id: str
    runner_token_plain_once: str


def _normalize_tags(tags: list[str] | None) -> list[str]:
    return sorted({str(tag).strip() for tag in (tags or []) if str(tag).strip()})


def register_runner(
    repo: Repository,
    tenant_id: str,
    *,
    name: str | None,
    tags: list[str] | None,
) -> RegisteredRunner:
    token = secrets.token_urlsafe(32)
    now = _utcnow_naive()
    runner_id = str(uuid4())
    data = RunnerCreateData(
        id=runner_id,
        name=(name.strip() if name and name.strip() else None),
        tags_json=_normalize_tags(tags),
        status="ONLINE",
        last_seen_at=now,
        token_hash=hash_secret(token),
        created_at=now,
        updated_at=now,
    )
    with repo.session() as s:
        repo.create_runner_in_session(s, tenant_id, data)
    return RegisteredRunner(runner_id=runner_id, runner_token_plain_once=token)


def authenticate_runner_in_session(repo: Repository, s, tenant_id: str, runner_id: str, token: str) -> RunnerRow:
    runner = repo.get_runner_in_session(s, tenant_id, runner_id)
    if runner is None:
        raise NotFoundError("Runner not found")
    if not token or not verify_secret(token, runner.token_hash):
        raise UseCaseValidationError("Invalid runner token")
    return runner


def heartbeat_runner(repo: Repository, tenant_id: str, runner_id: str, token: str) -> None:
    now = _utcnow_naive()
    with repo.session() as s:
        runner = authenticate_runner_in_session(repo, s, tenant_id, runner_id, token)
        runner.status = "ONLINE"
        runner.last_seen_at = now
        runner.updated_at = now


def list_runners(repo: Repository, tenant_id: str) -> list[RunnerRow]:
    return repo.list_runners(tenant_id)
