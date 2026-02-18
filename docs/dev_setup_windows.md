# Dev setup on Windows (PowerShell/CMD)

Эта инструкция — “как поднять проект с нуля на Windows” и **не застрять** на env/скриптах/SQLite/Alembic.

---

## 0) Что должно быть установлено

Минимум:
- **Git** (для `git clone`, `git pull`)
- **Python 3.11+** (если не используешь conda)
- или **Miniconda/Anaconda** (рекомендуется, чтобы изолировать env)
- **VS Code** (опционально, но удобно)

Проверка в терминале:

```powershell
git --version
python --version
```

---

## 1) Клонировать репозиторий и перейти в папку

```powershell
cd $HOME\Desktop
git clone <YOUR_REPO_URL>
cd .\data-decision-layer
```

---

## 2) Создать и активировать окружение

### Вариант A — conda (рекомендуется)
```powershell
conda create -n decision python=3.11 -y
conda activate decision
```

### Вариант B — venv
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Проверка:
```powershell
python --version
pip --version
```

---

## 3) Установить зависимости

```powershell
pip install -r requirements.txt
```

---

## 4) Запуск API (самый простой способ)

### Вариант A — PowerShell “одной кнопкой”
Из корня репозитория:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

Что делает скрипт:
- гарантирует `data/`
- выставляет `DDW_DB_URL` на `./data/ddw.db`
- накатывает Alembic миграции
- поднимает `uvicorn` с `--reload`

### Вариант B — CMD “одной кнопкой”
Открой **cmd.exe** и из корня репозитория:

```bat
scripts\dev.bat
```

### Вариант C — вручную (для дебага)
```powershell
$env:DDW_DB_URL = "sqlite+pysqlite:///./data/ddw.db"
python -m alembic upgrade head
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

---

## 5) Проверка, что сервер жив

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Swagger UI:
- `http://127.0.0.1:8000/docs`

---

## 6) База данных SQLite (ddw.db)

- Файл `ddw.db` — **локальный артефакт разработки**, в git не коммитится (`*.db` в `.gitignore`).
- Рекомендуемое расположение: `./data/ddw.db`.
- Относительный путь считается от текущей директории, поэтому запускать `uvicorn` лучше **из корня репозитория** (скрипты делают это автоматически).

---

## 7) Команды качества (Definition of Done)

Из корня репо:

```powershell
ruff check .
mypy .
pytest -q
```

---

## 8) Частые проблемы (и быстрые фиксы)

### 8.1 PowerShell ругается на ExecutionPolicy
Ошибка типа “running scripts is disabled”.

Решение (без админ-прав, только для текущего запуска):
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

(Не меняет глобальные политики — безопасно.)

### 8.2 `export DDW_DB_URL=...` не работает
`export` — это bash. В PowerShell надо так:

```powershell
$env:DDW_DB_URL = "sqlite+pysqlite:///./data/ddw.db"
```

### 8.3 `Internal Server Error` при записи в БД
90% случаев: миграции не накатили.

```powershell
python -m alembic upgrade head
python -m alembic current
```

### 8.4 `Address already in use` (порт занят)
Либо убей процесс на 8000, либо запусти на другом порту.

PowerShell:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 -Port 8001
```

CMD:
```bat
scripts\dev.bat 8001
```

### 8.5 `ModuleNotFoundError: core/store/use_cases/api`
Ты запускаешь не из корня репозитория.

Правильно:
- `cd ...\data-decision-layer`
- и уже оттуда `pytest`, `uvicorn`, `alembic`

---

## 9) Мини sanity-check API (быстро)

```powershell
# tenant обязателен для /api/v1/*
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/errors" `
  -Headers @{ "Content-Type"="application/json"; "X-Tenant-Id"="tenantA" } `
  -Body '{"y_true":"cat","y_pred":"dog","confidence":0.73,"context":{"note":"sanity"}}'
```

Проверка list (pagination+filters):
```powershell
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:8000/api/v1/errors?limit=2&offset=0&y_true=cat" `
  -Headers @{ "X-Tenant-Id"="tenantA" }
```
