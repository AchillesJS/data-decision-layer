# Data Decision Layer — Decision Workspace for ML Data Decisions

## Что это за проект (в 1 минуту)

**Data Decision Layer** — это **Decision Workspace for ML data decisions**.

Это НЕ:
- tool
- engine
- AI
- auto-ML
- “улучшатель моделей”

Это **рабочее пространство для принятия решений в условиях неопределённости**, которое:
- превращает хаотичное “мы не понимаем, что происходит”  
  в ограниченное и аргументированное пространство решений
- делает неопределённость видимой
- формирует гипотезы (не выводы)
- связывает действия с гипотезами, риском и стоимостью
- ведёт историю решений через **Decision Record / Backlog**

Канон продукта: `docs/canon.md`  
Never/анти-фичи: `docs/anti_features.md`

---

## Где это в ML pipeline

Data → Train → Evaluate → DECISION WORKSPACE → Data actions → Retrain

Мы не “улучшаем модель напрямую”.  
Мы улучшаем **качество решений о данных ДО train()**.

---

## Статус проекта

Сейчас настроены базовые вещи, чтобы разработка шла без хаоса:

- репозиторий и структура проекта
- окружение Python (conda)
- зависимости
- тесты (`pytest`)
- линтер (`ruff`)
- проверка типов (`mypy`)
- скрипты “одной кнопкой” (`scripts/*.bat`)
- sample dataset (`data/sample_errors.csv`)
- skeleton миграций Alembic (`store/migrations`) + `alembic.ini`

На этом этапе мы **готовы начинать MVP**, когда примем решение “стартуем”.

---

## Жёсткие правила (чтобы не уплыть)

### Источник истины
- Canon: `docs/canon.md`
- Anti-features (NEVER): `docs/anti_features.md`
- Любое изменение смысла продукта — сначала в docs, потом в код.

### Слойность
- `core/` — доменная логика и инварианты (без DB, без API)
- `store/` — хранение (DB/репозитории/миграции)
- `api/` — транспорт (FastAPI)
- `ui/` — интерфейс (позже)

**Бизнес-логики в `api/` и `ui/` быть не должно.**

### Каждое изменение = проверка
Перед любым пушем:
- тесты
- линт
- (по возможности) типы

---

## Структура репозитория

data-decision-layer/
├── core/ # доменные объекты (Pydantic), инварианты
│ ├── init.py
│ └── error.py
│
├── store/ # DB слой (позже: models, repository, migrations)
│ └── migrations/ # Alembic init
│ ├── env.py
│ ├── script.py.mako
│ └── versions/
│
├── api/ # FastAPI слой (транспорт)
│ └── main.py
│
├── ui/ # UI (позже)
│ └── app.py
│
├── tests/ # pytest
│ ├── init.py
│ └── test_core_objects.py
│
├── docs/
│ ├── canon.md
│ └── anti_features.md
│
├── data/
│ └── sample_errors.csv
│
├── scripts/ # “кнопки” запуска/проверок (Windows)
│ ├── run_api.bat
│ ├── test.bat
│ ├── lint.bat
│ └── typecheck.bat
│
├── alembic.ini # конфиг alembic (SQLite url)
├── pyproject.toml # конфиг pytest/ruff/mypy
├── requirements.txt # зависимости
└── README.md

---

## Быстрый старт (Windows + conda)

### 0) Открыть терминал
Лучше всего: **Anaconda Prompt** или терминал в VS Code.

Перейти в папку проекта:
```bat
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
Команды проекта (одна кнопка)
Тесты
scripts\test.bat
Линтер (ruff)
scripts\lint.bat
Типы (mypy)
scripts\typecheck.bat
Запуск API
scripts\run_api.bat
________________________________________
Что означает “зелёный проект”
Проект считается “готов к работе”, если:
1.	scripts\test.bat — проходит
2.	scripts\lint.bat — без ошибок
3.	scripts\typecheck.bat — без ошибок
4.	API запускается (scripts\run_api.bat)
________________________________________
Git: как работать (простая дисциплина)
Проверить состояние
git status
Добавить все изменения в коммит
git add .
Закоммитить
git commit -m "feat: short description"
Отправить на GitHub
git push
Полезно смотреть что меняется
git diff
________________________________________
Alembic (миграции) — что это и как использовать (когда начнём DB)
Сейчас Alembic только инициализирован (рельсы готовы).
Где конфиг
alembic.ini
Сейчас настроено:
sqlalchemy.url = sqlite:///data/app.db
Важно
Пока у нас нет ORM моделей — миграции не запускаем.
Когда начнём DB слой:
•	добавим store/models.py
•	подключим Base.metadata в store/migrations/env.py
•	сделаем:
o	alembic revision --autogenerate -m "create tables"
o	alembic upgrade head
________________________________________
Sample data
Файл: data/sample_errors.csv
Он нужен, чтобы потом проверять ingest/поток без внешних интеграций.
Формат колонок:
•	y_true
•	y_pred
•	confidence
•	slice_json (JSON строка с метаданными среза)
•	example_ref (ссылка/путь/хэш на пример)
________________________________________
Частые проблемы и быстрые решения
1) ModuleNotFoundError: No module named 'core'
Решение: убедись, что есть файлы:
•	core/__init__.py
•	tests/__init__.py
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
Как мы будем начинать MVP (когда скажем “старт”)
Мы начнём с минимально безопасного пути:
1.	core/ — доменные контракты (уже есть Error)
2.	store/ — минимальная БД схема (errors) + репозиторий
3.	api/ — минимальные эндпоинты для чтения/записи
4.	Decision Record как главный артефакт (история решений)
Важно: продукт выдаёт гипотезы, не “истины”.
________________________________________
Ссылки внутри проекта
•	Canon: docs/canon.md
•	Anti-features (NEVER): docs/anti_features.md
________________________________________
Лицензия
TBD (пока private repo)


