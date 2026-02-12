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

---

## Где это в ML pipeline

Data → Train → Evaluate → DECISION WORKSPACE → Data actions → Retrain

Мы не “улучшаем модель напрямую”.
Мы улучшаем качество решений о данных ДО train().

---

## Статус проекта

Сейчас настроены базовые вещи, чтобы разработка шла без хаоса:

- репозиторий и структура проекта
- окружение Python (conda)
- зависимости
- тесты (pytest)
- линтер (ruff)
- проверка типов (mypy)
- скрипты “одной кнопкой” (scripts/*.bat)
- sample dataset (data/sample_errors.csv)
- skeleton миграций Alembic (store/migrations) + alembic.ini

И главное: уже оформлено ядро продукта и начата “склейка” слоёв:

### Core (готово как доменные контракты)
В `core/` описаны доменные сущности (Pydantic) + статусы + инварианты:
- Error
- Hypothesis
- Action
- DecisionRecord
- DataPotential

### Store (в работе, но уже есть базовая реализация)
В `store/` есть:
- `store/models.py` — ORM модели
- `store/repository.py` — репозиторий и операции чтения/записи (включая session-aware методы)

### Use cases (появились и уже используются)
`use_cases/` — слой orchestration, где живут:
- проверки ссылочной целостности
- проверки переходов статусов по `docs/state_machine.md`
- операции “в одну транзакцию”
- правила “Action ↔ Hypothesis” и т.п.

### Tests (расширены)
Кроме тестов core добавлен тест на целостность use-cases:
- `tests/test_core_objects.py`
- `tests/test_use_cases_integrity.py`

На этом этапе мы не “подготавливаемся абстрактно” — мы уже на треке MVP:
ядро описано, хранилище и use_cases заведены, тесты есть, документация фиксирует границы.

---

## Жёсткие правила (чтобы не уплыть)

### Источник истины
- Canon: `docs/canon.md`
- Anti-features (NEVER): `docs/anti_features.md`
- State machine: `docs/state_machine.md`
- Любое изменение смысла продукта — сначала в docs, потом в код.

### Слойность (важное уточнение по текущей архитектуре)
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

## Структура репозитория (актуально по текущим файлам)
```text
data-decision-layer/
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
│  └─ migrations/ # Alembic init
│     ├─ env.py
│     ├─ script.py.mako
│     └─ versions/
├─ use_cases/ # orchestration + проверки + переходы статусов (строго здесь)
│  ├─ __init__.py
│  ├─ transitions.py
│  ├─ hypotheses.py
│  ├─ actions.py
│  ├─ decision_records.py
│  └─ archive.py
├─ api/   # FastAPI слой (транспорт)
│  └─ main.py
├─ ui/    # UI (позже)
│  └─ app.py
├─ tests/ # pytest
│  ├─ __init__.py
│  ├─ test_core_objects.py
│  └─ test_use_cases_integrity.py
├─ docs/
│  ├─ canon.md
│  ├─ anti_features.md
│  └─ state_machine.md
├─ data/
│  ├─ sample_errors.csv
│  └─ app.db   # локальная sqlite БД (НЕ коммитить)
├─ scripts/ # "кнопки" запуска/проверок (Windows)
│  ├─ run_api.bat
│  ├─ test.bat
│  ├─ lint.bat
│  └─ typecheck.bat
├─ alembic.ini      # конфиг alembic (SQLite url)
├─ pyproject.toml   # конфиг pytest/ruff/mypy
├─ requirements.txt # зависимости
└─ README.md
```
---

## Быстрый старт (Windows + conda)

0) Открыть терминал  
Лучше всего: Anaconda Prompt или терминал в VS Code.

Перейти в папку проекта:
cd %USERPROFILE%\Desktop\data-decision-layer

1) Активировать окружение  
Если окружение уже создано:
conda activate decision

Если окружения ещё нет (на другом ПК):
conda create -n decision python=3.11 -y
conda activate decision

2) Установить зависимости
pip install -r requirements.txt

________________________________________
## Команды проекта (одна кнопка)

Тесты:
scripts\test.bat

Линтер (ruff):
scripts\lint.bat

Типы (mypy):
scripts\typecheck.bat

Запуск API:
scripts\run_api.bat

________________________________________
## Что означает “зелёный проект”

Проект считается “готов к работе”, если:
1) scripts\test.bat — проходит
2) scripts\lint.bat — без ошибок
3) scripts\typecheck.bat — без ошибок
4) API запускается (scripts\run_api.bat)

________________________________________
## Git: как работать (простая дисциплина)

Проверить состояние:
git status

Посмотреть что изменилось:
git diff

Добавить все изменения в коммит:
git add .

Закоммитить:
git commit -m "feat: short description"

Отправить на GitHub:
git push

________________________________________
## Alembic (миграции) — что это и как использовать (когда начнём DB полноценно)

Сейчас Alembic инициализирован (рельсы готовы).

Где конфиг:
alembic.ini

Сейчас настроено:
sqlalchemy.url = sqlite:///data/app.db

Важно:
- локальную БД `data/app.db` НЕ коммитим в git
- пока схема активно меняется — миграции используем аккуратно (минимум автогенерации без проверки)

Когда фиксируем DB слой:
• добавляем/уточняем store/models.py
• подключаем Base.metadata в store/migrations/env.py
• делаем:
  - alembic revision --autogenerate -m "create tables"
  - alembic upgrade head

________________________________________
## Sample data

Файл: data/sample_errors.csv  
Он нужен, чтобы проверять ingest/поток без внешних интеграций.

Формат колонок:
• y_true
• y_pred
• confidence
• slice_json (JSON строка с метаданными среза)
• example_ref (ссылка/путь/хэш на пример)

________________________________________
## Частые проблемы и быстрые решения

1) ModuleNotFoundError: No module named 'core'  
Решение: убедись, что есть файлы:
• core/__init__.py  
• tests/__init__.py  
И запускай тесты из корня репо.

2) ruff ругается на авто-сгенерированный файл Alembic  
Обычно лечится автофиксом:
ruff check . --fix

3) Conda не в PATH  
Решение: запускай команды из Anaconda Prompt.
Там conda уже доступна.

4) Uvicorn: Attribute "app" not found in module "api.main"  
Проверь, что в api/main.py есть переменная:
app = FastAPI()
И запуск:
uvicorn api.main:app --reload

________________________________________
## Как мы продолжаем MVP (текущее направление)

Мы идём по безопасному пути:
1) core/ — доменные контракты (готово)
2) use_cases/ — оркестрация и проверки по state_machine (в работе)
3) store/ — стабильная схема + репозиторий
4) tests/ — сквозные тесты на целостность (уже есть)
5) api/ — минимальные эндпоинты поверх use_cases (расширяем позже)

Важно: продукт выдаёт гипотезы, не “истины”.

________________________________________
## Ссылки внутри проекта
• Canon: docs/canon.md  
• Anti-features (NEVER): docs/anti_features.md  
• State machine: docs/state_machine.md  

________________________________________
## Лицензия
TBD (пока private repo)
