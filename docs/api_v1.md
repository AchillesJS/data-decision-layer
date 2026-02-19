# API v1 (FastAPI) — Data Decision Workspace

Эта документация описывает PUBLIC REST API v1 backend MVP для Data Decision Layer.

## Принципы

- API — **тонкий транспорт**: никакой бизнес-логики и целостности в роутерах.
- Все проверки/инварианты — только в `use_cases/` и `core/`.
- Наружу возвращаем **только Pydantic DTO** (никаких ORM entities).

## Multi-tenant

- tenant_id приходит из заголовка: `X-Tenant-Id`
- `X-Tenant-Id` **обязателен для всех запросов**, кроме `GET /health`
- Внутри API tenant_id прокидывается в use-cases и repo.

Если `X-Tenant-Id` отсутствует → `422 Missing X-Tenant-Id header`.

## Base URL

Локально:
- `http://127.0.0.1:8000`

Swagger UI:
- `http://127.0.0.1:8000/docs`

## Endpoints (MVP)

### Health
- `GET /health`

### Errors
- `POST /api/v1/errors`
- `GET  /api/v1/errors`
- `GET  /api/v1/errors/{id}`



**Query params для `GET /api/v1/errors`:**
- `limit` (int, default `50`, `1..200`)
- `offset` (int, default `0`, `>=0`)
- `status` (str, optional)
- `y_true` (str, optional)
- `y_pred` (str, optional)

### Hypotheses
- `POST /api/v1/hypotheses`
- `GET  /api/v1/hypotheses/{id}`

### Actions
- `POST /api/v1/actions`
- `GET  /api/v1/actions`
- `GET  /api/v1/actions/{id}`
- `POST /api/v1/actions/{id}/archive`

**Query params для `GET /api/v1/actions`:**
- `limit` (int, default `50`, `1..200`)
- `offset` (int, default `0`, `>=0`)
- `status` (str, optional)
- `hypothesis_id` (str, optional)

### Decision Records
- `POST /api/v1/decision-records`
- `GET  /api/v1/decision-records`
- `GET  /api/v1/decision-records/{id}`

**Query params для `GET /api/v1/decision-records`:**
- `limit` (int, default `50`, `1..200`)
- `offset` (int, default `0`, `>=0`)
- `decision` (str, optional) — `proceed | defer | reject`
- `made_by` (str, optional)

## Ошибки (HTTP mapping)

- `422` — missing `X-Tenant-Id`
- `404` — not found (в рамках tenant)
- `409` — integrity conflict (R1/R2/R3, cross-tenant references, forbidden transitions)
- `422` — validation (Pydantic)

## Частая причина 422: enum-поля

Некоторые поля принимают только фиксированные значения:

- `Action.risk_if_false`: `low | medium | high | critical`
- `Action.status`: `draft | proposed | approved | in_progress | done | cancelled`
  - если создаёшь Action без `hypothesis_id` — используй `status="draft"`
- `DecisionRecord.decision`: `proceed | defer | reject`

## Запуск локально (Windows PowerShell)

Из корня репозитория:

```powershell
$env:DDW_DB_URL = "sqlite+pysqlite:///./data/ddw.db"
python -m alembic upgrade head
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

## Примеры запросов (PowerShell)

### 1) Health
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
```

### 2) Create Error (tenantA)
```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/errors" `
  -Headers @{ "Content-Type"="application/json"; "X-Tenant-Id"="tenantA" } `
  -Body '{"y_true":"cat","y_pred":"dog","confidence":0.73,"context":{"note":"test"}}'
```

### 3) Read Error (tenantA)
```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:8000/api/v1/errors/<ERROR_ID>" `
  -Headers @{ "X-Tenant-Id"="tenantA" }
```

### 4) Create Action (draft, без hypothesis_id)
Важно: если `hypothesis_id` не указан — **Action должен быть draft**.

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/actions" `
  -Headers @{ "Content-Type"="application/json"; "X-Tenant-Id"="tenantA" } `
  -Body '{"status":"draft","name":"Relabel slice","description":"test","risk_if_false":"low","cost":{"time_hours":1},"expected_artifacts":["labels_v2.csv"]}'
```

### 5) Archive Action
```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/actions/<ACTION_ID>/archive" `
  -Headers @{ "X-Tenant-Id"="tenantA" }
```

### 6) Create DecisionRecord (decision enum)
`decision` принимает только: `proceed | defer | reject`.

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/decision-records" `
  -Headers @{ "Content-Type"="application/json"; "X-Tenant-Id"="tenantA" } `
  -Body '{"made_by":"sos","decision":"proceed","confidence":0.8,"rationale":"test","notes":"ok","hypothesis_ids":[],"action_ids":["<ACTION_ID>"],"error_ids":[]}'
```

## Smoke сценарий (как в tests/test_api_smoke.py)

1) Создать Error в tenant A → получить его  
2) Попытка получить его с tenant B → `404`  
3) Создать Action в tenant A  
4) Попробовать создать DecisionRecord в tenant B с `action_id` из tenant A → `409`

## Про sqlite файл (ddw.db)

Файл sqlite — локальный артефакт разработки.

Рекомендация: хранить локальные базы в `data/`:
- так понятнее, что это dev-артефакт
- `.gitignore` уже игнорирует `*.db`, поэтому БД не уйдёт в git

Важно: `sqlite+pysqlite:///./data/ddw.db` — **относительный путь**, он считается от текущей директории (cwd),
поэтому запускать `uvicorn` нужно из корня репозитория.
