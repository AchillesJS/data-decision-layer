# Data Decision Layer — Decision Workspace for ML Data Decisions

## Что это за проект

Data Decision Layer — это Decision Workspace for ML data decisions.

Это НЕ:
- tool
- engine
- AI
- auto-ML
- “улучшатель моделей”

Это рабочее пространство для принятия решений в условиях неопределённости, которое:
- превращает хаотичное “мы не понимаем, что происходит”
  в ограниченное и аргументированное пространство решений
- делает неопределённость видимой
- формирует гипотезы (не выводы)
- связывает действия с гипотезами, риском и стоимостью
- ведёт историю решений через Decision Record / Backlog

Канон продукта: `docs/canon.md`  
Never/анти-фичи: `docs/anti_features.md`  
State machine (статусы/переходы): `docs/state_machine.md`  
API v1 (FastAPI): `docs/api_v1.md`

---

## Где это в ML pipeline

Data → Train → Evaluate → DECISION WORKSPACE → Data actions → Retrain

Мы не “улучшаем модель напрямую”.
Мы улучшаем качество решений о данных ДО train().

---

## Статус проекта

Проект находится в состоянии **backend MVP**: есть доменная модель, store, use-cases и PUBLIC REST API v1.

Сейчас настроены базовые вещи, чтобы разработка шла без хаоса:

- репозиторий и структура проекта
- окружение Python (conda)
- зависимости
- тесты (pytest)
- линтер (ruff)
- проверка типов (mypy)
- скрипты запуска/проверок (Windows)
- skeleton миграций Alembic (store/migrations) + alembic.ini
- PUBLIC REST API v1 (FastAPI) с multi-tenant

И главное: оформлено ядро продукта и “склейка” слоёв.

### Core (готово как доменные контракты)
В `core/` описаны доменные сущности (Pydantic) + статусы + инварианты:
- Error
- Hypothesis
- Action
- DecisionRecord
- DataPotential

### Store (готово для MVP)
В `store/` есть:
- `store/models.py` — ORM модели
- `store/repository.py` — репозиторий и операции чтения/записи (tenant-aware)

### Use cases (готово и используется API)
`use_cases/` — слой orchestration, где живут:
- проверки ссылочной целостности (включая tenant boundaries)
- проверки переходов статусов по `docs/state_machine.md`
- операции “в одну транзакцию”

### API v1 (готово как thin transport)
`api/` — FastAPI слой **без бизнес-логики**, только транспорт:
- tenant_id обязателен через заголовок `X-Tenant-Id` (кроме `/health`)
- наружу возвращаются только Pydantic DTO (никаких ORM entities)
- ошибки домена маппятся в HTTP (`400/404/409/422`)
- smoke тесты: `tests/test_api_smoke.py`

---

## Жёсткие правила (чтобы не уплыть)

### Источник истины
- Canon: `docs/canon.md`
- Anti-features (NEVER): `docs/anti_features.md`
- State machine: `docs/state_machine.md`
- Любое изменение смысла продукта — сначала в docs, потом в код.

### Слойность
- `core/` — доменная логика и инварианты (без DB, без API)
- `store/` — хранение (DB/репозитории/миграции), без бизнес-логики
- `use_cases/` — ЕДИНСТВЕННОЕ место для orchestration/проверок/переходов статусов
- `api/` — транспорт (FastAPI)
- `ui/` — интерфейс (позже)

Бизнес-логики в `api/` и `ui/` быть не должно.  
Бизнес-логики в `store/` быть не должно (только persistence и маппинг).

### Каждое изменение = проверка
Перед любым пушем:
- тесты
- линт
- (по возможности) типы

---

## Структура репозитория (актуально)
```text
data-decision-layer/
├─ api/   # FastAPI слой (тонкий транспорт)
│  ├─ __init__.py
│  ├─ main.py
│  ├─ deps.py          # get_repo, get_tenant_id (X-Tenant-Id)
│  ├─ exceptions.py    # domain -> HTTP mapping
│  ├─ schemas/
│  │  ├─ __init__.py
│  │  ├─ error.py
│  │  ├─ hypothesis.py
│  │  ├─ action.py
│  │  └─ decision.py
│  └─ routers/
│     ├─ __init__.py
│     ├─ errors.py
│     ├─ hypotheses.py
│     ├─ actions.py
│     └─ decisions.py
├─ core/  # доменные объекты (Pydantic), статусы, инварианты
│  ├─ __init__.py
│  ├─ error.py
│  ├─ hypothesis.py
│  ├─ action.py
│  ├─ decision.py
│  └─ potential.py
├─ store/ # DB слой (SQLAlchemy), без бизнес-логики
│  ├─ __init__.py
│  ├─ models.py
│  ├─ repository.py
│  └─ migrations/ # Alembic
│     ├─ env.py
│     ├─ script.py.mako
│     └─ versions/
├─ use_cases/ # orchestration + проверки + переходы статусов (строго здесь)
│  ├─ __init__.py
│  ├─ transitions.py
│  ├─ errors.py
│  ├─ hypotheses.py
│  ├─ actions.py
│  ├─ decision_records.py
│  └─ archive.py
├─ tests/ # pytest
│  ├─ __init__.py
│  ├─ test_core_objects.py
│  ├─ test_use_cases_integrity.py
│  └─ test_api_smoke.py
├─ docs/
│  ├─ canon.md
│  ├─ anti_features.md
│  ├─ state_machine.md
│  └─ api_v1.md
├─ data/
│  ├─ sample_errors.csv
│  └─ ddw.db   # локальная sqlite БД (НЕ коммитить, *.db в .gitignore)
├─ scripts/ # "кнопки" запуска/проверок (Windows)
│  ├─ run_api.bat
│  ├─ test.bat
│  ├─ lint.bat
│  ├─ typecheck.bat
│  └─ dev.ps1        # PowerShell: env + migrations + uvicorn
├─ alembic.ini
├─ pyproject.toml
├─ requirements.txt
└─ README.md
```

---

## Быстрый старт (Windows + conda)

0) Открыть терминал  
Лучше всего: Anaconda Prompt или терминал в VS Code.

Перейти в папку проекта:
```bat
cd %USERPROFILE%\Desktop\data-decision-layer
```

1) Активировать окружение  
Если окружение уже создано:
```bat
conda activate decision
```

Если окружения ещё нет (на другом ПК):
```bat
conda create -n decision python=3.11 -y
conda activate decision
```

2) Установить зависимости
```bat
pip install -r requirements.txt
```

---

## Запуск API (Windows PowerShell)

### Вариант 1 — вручную (просто и прозрачно)

Из корня репозитория:

```powershell
# 1) указать локальную sqlite DB (рекомендуем хранить в data/)
$env:DDW_DB_URL = "sqlite+pysqlite:///./data/ddw.db"

# 2) накатить миграции
python -m alembic upgrade head

# 3) поднять API
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Проверка:
- `GET http://127.0.0.1:8000/health` → `{"status":"ok"}`
- Swagger UI: `http://127.0.0.1:8000/docs`

Важно:
- для всех `/api/v1/*` нужен заголовок `X-Tenant-Id` (кроме `/health`)

### Вариант 2 — одной командой (scripts/dev.ps1)

```powershell
.\scripts\dev.ps1
```

Если нужен другой порт:
```powershell
.\scripts\dev.ps1 -Port 8001
```


### Частая причина 422: enum-поля (фиксированные значения)

Если ты вручную шлёшь JSON (PowerShell/curl), помни: некоторые поля принимают **только** значения из enum.

- `Action.risk_if_false`: `low | medium | high | critical`
- `Action.status`: `draft | proposed | approved | in_progress | done | cancelled`
  - если создаёшь Action **без** `hypothesis_id` — ставь `status="draft"`, иначе словишь валидацию/конфликт
- `DecisionRecord.decision`: `proceed | defer | reject`

Подсказка: самый надёжный способ — открыть `http://127.0.0.1:8000/docs` и брать payload прямо из схем.


---

## Команды проекта (одна кнопка)

Тесты:
```bat
scripts\test.bat
```

Линтер (ruff):
```bat
scripts\lint.bat
```

Типы (mypy):
```bat
scripts\typecheck.bat
```

Запуск API (bat):
```bat
scripts\run_api.bat
```

Запуск API (PowerShell):
```powershell
.\scripts\dev.ps1
```

---

## Что означает “зелёный проект”

Проект считается “готов к работе”, если:
1) `pytest -q` — проходит
2) `ruff check .` — без ошибок
3) `mypy .` — без ошибок
4) API запускается и отвечает на `/health`

---

## Git: как работать (простая дисциплина)

Проверить состояние:
```bat
git status
```

Посмотреть что изменилось:
```bat
git diff
```

Добавить все изменения в коммит:
```bat
git add .
```

Закоммитить:
```bat
git commit -m "feat: short description"
```

Отправить на GitHub:
```bat
git push
```

---

## Alembic (миграции) — правила

- DB URL берётся из env-var `DDW_DB_URL`
- локальные `*.db` не коммитим (см. `.gitignore`)
- “источник истины” по схеме: `store/models.py` + миграции Alembic

Основные команды:
```powershell
python -m alembic current
python -m alembic upgrade head
```

---

## Sample data

Файл: `data/sample_errors.csv`  
Он нужен, чтобы проверять ingest/поток без внешних интеграций.

Формат колонок:
- y_true
- y_pred
- confidence
- slice_json (JSON строка с метаданными среза)
- example_ref (ссылка/путь/хэш на пример)

---

## Частые проблемы и быстрые решения

1) `ModuleNotFoundError: No module named 'core'`  
Решение: запускай тесты/uvicorn **из корня репо**.

2) PowerShell: `export` не работает  
Решение: в PowerShell задавай env так:
```powershell
$env:DDW_DB_URL = "sqlite+pysqlite:///./data/ddw.db"
```

3) `Uvicorn: Attribute "app" not found in module "api.main"`  
Проверь, что в `api/main.py` есть:
```python
app = FastAPI()
```
4) ruff ругается на авто-сгенерированный файл Alembic  
Обычно лечится автофиксом:
ruff check . --fix

5) Conda не в PATH  
Решение: запускай команды из Anaconda Prompt.
Там conda уже доступна.

6) `Internal Server Error` на запись в БД  
Чаще всего: не накатили миграции:
```powershell
python -m alembic upgrade head
```

---

## Как мы продолжаем MVP (текущее направление)

Мы идём по безопасному пути:
1) core/ — доменные контракты
2) use_cases/ — оркестрация и проверки по state_machine
3) store/ — схема + репозиторий
4) tests/ — сквозные тесты на целостность
5) api/ — минимальные эндпоинты поверх use_cases

Важно: продукт выдаёт гипотезы, не “истины”.

---

## Ссылки внутри проекта
- Canon: `docs/canon.md`  
- Anti-features (NEVER): `docs/anti_features.md`  
- State machine: `docs/state_machine.md`  
- API v1: `docs/api_v1.md`

---

## Лицензия
TBD (пока private repo)
