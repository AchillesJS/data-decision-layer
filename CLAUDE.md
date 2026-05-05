# DDW Claude Code Instructions

## Project identity

Data Decision Workspace (DDW) is a learning intelligence system for ML training decisions.

DDW reduces uncertainty in ML experimentation. It does not optimize models automatically and does not act as an oracle.

## Hard architecture rules

- Keep layers strict:
  - `core/` = domain objects and invariants only.
  - `store/` = SQLAlchemy models, migrations, repository, persistence only.
  - `use_cases/` = business rules, workflow, integrity checks.
  - `api/` = thin FastAPI transport only.
  - `analytics_engine/` = pure analytics/math, no DB/API.
  - `contracts/` = external payload contracts.
  - `runner_cli/` = runner/CLI code.
- Do not put business logic in API routers.
- Do not put analytics logic in `store/`.
- Do not import API from use_cases/store/core.
- Do not change `core/` unless explicitly requested.

## Canon rules

- DDW never claims root cause.
- DDW never gives exact accuracy/uplift predictions.
- All analytics outputs must include:
  - ranges, not single-point claims;
  - confidence;
  - assumptions;
  - evidence references.
- If evidence is insufficient, return `UNKNOWN`, `insufficient_data`, or a low-confidence result.
- Auto-generated hypotheses/checks must be drafts only and must require human acceptance.
- Use wording like:
  - “consistent with”
  - “suggests”
  - “possible check”
  - “check whether”
- Avoid wording like:
  - “root cause”
  - “the reason is”
  - “you should”
  - “recommendation”

## API rules

- All `/api/v1/*` endpoints require `X-Tenant-Id`, except `/health`.
- Public expected errors are only `404`, `409`, and `422`.
- Do not introduce `429`.
- API responses must use DTO schemas, never ORM rows.
- Keep routers thin: parse request, call use case, return DTO.

## Runner/Jobs rules

- Runner uses pull model only.
- DDW must not initiate inbound connections to runners.
- Logs/complete/metrics require valid `lease_token`.
- Expired or invalid lease returns `409`.
- Runner tokens must not be stored in plain text.
- Run reports must be validated before creating runs/metric points.
- `external_run_id` must be unique per tenant and idempotent.

## Testing rules

Before finishing any implementation, run:

```bash
pytest -q
ruff check .
mypy .
python -m alembic upgrade head
```

## Work style

- Implement one phase at a time.
- First provide a patch plan.
- Do not implement future phases unless explicitly asked.
- Prefer minimal patches over rewrites.
- Do not add dependencies unless necessary.