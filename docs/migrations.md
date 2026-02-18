# Database Migrations (Alembic)

Этот проект использует **Alembic** для управления миграциями схемы БД (SQLite).

## Канон и ограничения

- **store/** отвечает только за persistence (таблицы/ORM-модели/репозиторий).
- **use_cases/** отвечает за правила целостности и оркестрацию.
- Миграции **не содержат бизнес-логики** и не трогают `core/` и `use_cases/`.
- **Физический delete запрещён** на уровне продукта (мы используем `ARCHIVED`), но миграции могут менять схему (DDL).

## Где лежит Alembic

- Конфиг: `alembic.ini`
- Миграции: `store/migrations/`
  - `store/migrations/env.py` — настройка окружения
  - `store/migrations/versions/` — версии миграций (например `0001_init.py`)

## Важно: один DB URL для всего проекта

Частая ошибка: прогнали миграции в одну SQLite-базу, а приложение использует другую.

Проверь, что **один и тот же DB URL** используется:
- Alembic: `alembic.ini` → `sqlalchemy.url`
- Приложение: `Repository.sqlite(url=...)` / конфиг приложения

Рекомендация: держать URL в одном месте (env-var), например:
- `DDW_DB_URL=sqlite+pysqlite:///./workspace.db`

И использовать его и в Alembic, и в приложении.

## Быстрый старт

### 1) Применить миграции
Из корня репозитория:

```bash
alembic upgrade head
````

### 2) Посмотреть текущую версию

```bash
alembic current
```

### 3) Посмотреть историю

```bash
alembic history
```

## Как добавлять новую миграцию

### Правило №1: миграция = изменение схемы store

Если меняется `store/models.py` (таблицы/колонки/индексы/constraints) — добавляем миграцию.

### Вариант A (рекомендуется): autogenerate

1. Внеси изменения в `store/models.py`
2. Сгенерируй миграцию:

```bash
alembic revision --autogenerate -m "add <thing>"
```

3. Открой новый файл в `store/migrations/versions/` и проверь:

* правильные таблицы/колонки
* нет случайного drop/create там, где должен быть alter
* нет “лишних” изменений из-за default/nullable

4. Прогони:

```bash
alembic upgrade head
pytest -q
```

### Вариант B: ручная миграция (если autogenerate запрещён)

1. Создай пустую ревизию:

```bash
alembic revision -m "add <thing>"
```

2. Заполни `upgrade()`/`downgrade()` вручную, используя `op.create_table`, `op.add_column`, `op.create_index`, и т.д.
3. Прогони:

```bash
alembic upgrade head
pytest -q
```

## SQLite нюансы

* SQLite ограничен по DDL (ALTER TABLE). Поэтому в `env.py` включён **batch mode**:

  * `render_as_batch=True`
* Это нормально и ожидаемо.

## Политика downgrade

MVP-политика (простая и честная):

* downgrade поддерживаем на “best effort”.
* если миграция необратима (например, drop column), явно документируем это в комментарии внутри миграции.

## Smoke test миграций

В проекте должен быть тест, который гарантирует:

* на чистой БД `alembic upgrade head` проходит
* основные таблицы существуют

Смотри: `tests/test_migrations_smoke.py`

## Типы и JSON поля

Если используются JSON-like поля (SQLite):

* хранение через TEXT + `json.dumps/json.loads` или SQLAlchemy JSON type, совместимый с SQLite.

Важно:

* не ломать совместимость старых миграций “случайной” сменой внутренней реализации типа.
* если появляется кастомный тип (например `JSONText`), лучше фиксировать его поведение и менять очень осторожно.

## Чеклист перед merge

* `pytest -q` зелёный
* `ruff check .` зелёный
* `mypy .` зелёный
* `alembic upgrade head` проходит на чистой БД
* DB URL единый для Alembic и приложения


