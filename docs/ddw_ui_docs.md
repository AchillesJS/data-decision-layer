# DDW UI (Streamlit) — Docs (single file)

UI для Data Decision Workspace (DDW), работающий **только через HTTP API v1**.  
UI не лезет в БД напрямую и не меняет backend.

---

## Содержание
- [1. Контракт и инварианты](#1-контракт-и-инварианты)
- [2. Экраны UI](#2-экраны-ui)
- [3. Конфиг UI](#3-конфиг-ui)
- [4. Запуск](#4-запуск)
- [5. Endpoints, которые использует UI](#5-endpoints-которые-использует-ui)
- [6. Obsidian-ish Notes Vault (локальные заметки)](#6-obsidian-ish-notes-vault-локальные-заметки)
- [7. Troubleshooting](#7-troubleshooting)
- [8. Важно про Potentials transition](#8-важно-про-potentials-transition)

---

## 1) Контракт и инварианты

- **UI = тонкий HTTP-клиент**: общается только с REST API v1.
- **Tenant обязателен:** каждый запрос UI (кроме `/health`) отправляет заголовок:
  - `X-Tenant-Id: <TENANT_ID>`
- **Контракт ошибок:** UI ожидает только `404 / 409 / 422`.
- **Никаких stacktrace пользователю:** UI показывает только нормализованную ошибку:
  - `404/409`: строка `detail`
  - `422`: список ошибок (loc/msg/type)

---

## 2) Экраны UI

### 2.1 Dashboard
- Счётчики: Hypotheses / Actions / Potentials (**не archived**) + Decisions (последние 10)
- Таблица последних DecisionRecords (последние 10)
- Быстрый просмотр деталей DecisionRecord

### 2.2 Hypotheses → Actions
- Список гипотез + фильтр по status
- Create hypothesis (форма)
- Детали hypothesis:
  - поля (в т.ч. markdown-рендер statement/description/notes)
  - список действий по `hypothesis_id`
  - create action (форма)
  - archive hypothesis / archive action
  - transition (если endpoint существует и допустим по статусу)

### 2.3 Potentials
- Список potentials + фильтр по status
- Create potential (форма: range 0..1 + confidence + assumptions + limiting_factors + evidence refs)
- Детали potential (карточка: range/confidence/evidence)
- Archive potential

---

## 3) Конфиг UI

UI держит в `st.session_state` и показывает в сайдбаре:

- `BASE_URL` (default: `http://127.0.0.1:8000`)
- `TENANT_ID` (default: `tenantA`)

---

## 4) Запуск

### 4.1 Windows / PowerShell

#### Backend (терминал №1)
```powershell
conda activate decision
$env:DDW_DB_URL = "sqlite+pysqlite:///./data/ddw.db"

python -m alembic upgrade head
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Проверка:
- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

#### UI (терминал №2)
```powershell
conda activate decision
streamlit run ui/app.py
```

Если `streamlit` не находится как команда:
```powershell
python -m streamlit run ui/app.py
```

Откроется:
- `http://localhost:8501`

#### Настройки в UI
В сайдбаре выставь:
- `BASE_URL = http://127.0.0.1:8000`
- `TENANT_ID = tenantA` (или свой tenant)

---

## 5) Endpoints, которые использует UI

Все запросы (кроме `/health`) отправляются с заголовками:

- `X-Tenant-Id: <TENANT_ID>`
- `Content-Type: application/json`

UI использует `X-Total-Count` из заголовков list-endpoints для счётчиков.

### 5.1 Dashboard
- `GET /api/v1/hypotheses?limit=1&offset=0`
- `GET /api/v1/hypotheses?limit=1&offset=0&status=archived`

- `GET /api/v1/actions?limit=1&offset=0`
- `GET /api/v1/actions?limit=1&offset=0&status=archived`

- `GET /api/v1/potentials?limit=1&offset=0`
- `GET /api/v1/potentials?limit=1&offset=0&status=archived`

- `GET /api/v1/decision-records?limit=10&offset=0`
- `GET /api/v1/decision-records/{id}`

### 5.2 Hypotheses
- `GET  /api/v1/hypotheses?limit=50&offset=0&status=...`
- `POST /api/v1/hypotheses`
- `GET  /api/v1/hypotheses/{id}`
- `POST /api/v1/hypotheses/{id}/transition`
- `POST /api/v1/hypotheses/{id}/archive`

### 5.3 Actions
- `GET  /api/v1/actions?limit=50&offset=0&hypothesis_id=...`
- `POST /api/v1/actions`
- `GET  /api/v1/actions/{id}`
- `POST /api/v1/actions/{id}/transition`
- `POST /api/v1/actions/{id}/archive`

### 5.4 Potentials
- `GET  /api/v1/potentials?limit=50&offset=0&status=...`
- `POST /api/v1/potentials`
- `GET  /api/v1/potentials/{id}`
- `POST /api/v1/potentials/{id}/archive`

---

## 6) Obsidian-ish Notes Vault (локальные заметки)

Этот режим — “второй слой” поверх API: ты ведёшь заметки как в Obsidian, но:
- **API остаётся источником истины** по статусам/полям сущностей
- заметки **не пишутся в backend**, а сохраняются локально на диск

### 6.1 Где хранятся заметки

По умолчанию:
```
ui/.vault/<tenant_id>/<entity>/<id>.md
```

Примеры:
- `ui/.vault/tenantA/hypothesis/<uuid>.md`
- `ui/.vault/tenantA/action/<uuid>.md`
- `ui/.vault/tenantA/potential/<uuid>.md`

### 6.2 Что в заметках
- Markdown свободной формы
- Можно вставить шаблон (snapshot + поля из API) и дописать своё

### 6.3 Что важно
- Это локальный слой (как Obsidian vault), не синхронизируется сам по себе.
- Для синхронизации: положи `ui/.vault` под git (или в отдельный приватный репо), либо используй облачную папку/диск.

### 6.4 Как сбросить заметки
Удалить папку:
```
ui/.vault/
```
UI создаст её заново при следующем сохранении заметки.

---

## 7) Troubleshooting

### 7.1 `streamlit` not recognized (Windows)
Проверь, что Streamlit установлен именно в твоём env и запусти через модуль:
```powershell
conda activate decision
python -m pip show streamlit
python -m streamlit run ui/app.py
```

Если не установлен — лучше через conda-forge:
```powershell
conda install -c conda-forge streamlit -y
```

### 7.2 `pip install streamlit` падает с `ConnectionResetError(10054)`
Это сеть/прокси режет PyPI. Используй зеркало:
```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn streamlit
```

### 7.3 UI пишет “API unreachable”
- Проверь что backend запущен: `uvicorn api.main:app --reload`
- Проверь `BASE_URL` в UI: `http://127.0.0.1:8000`
- Проверь `/health` в браузере

### 7.4 422 “Missing X-Tenant-Id header”
TENANT_ID пустой или UI не прокинул header.
- В сайдбаре установи `TENANT_ID`, например `tenantA`
- Нажми “Refresh data”

### 7.5 422 на create/transition
Это нормальная валидация инвариантов доменной модели.
UI показывает таблицу ошибок (loc/msg/type), без stacktrace.

Практика:
- сначала создавай сущности в `draft`
- потом переходи статусами (transition), когда заполнил нужные поля

### 7.6 404 на `potentials/{id}/transition`
В API v1 может не быть transition для potentials.
Правильно: только `POST /api/v1/potentials/{id}/archive`.

---

## 8) Важно про Potentials transition

Если в твоём backend **нет** endpoint:
- `POST /api/v1/potentials/{id}/transition`

то UI должен **не показывать** кнопку transition для Potentials (иначе будет 404).  
Остаётся только:
- `POST /api/v1/potentials/{id}/archive`

(Если позже transition появится — UI можно включить обратно, это чисто UI-логика.)
