# Alembic в Data Decision Workspace

Этот документ объясняет, как устроены миграции Alembic в проекте и какой **правильный рабочий процесс** использовать.

---

## Зачем Alembic в этом проекте

Alembic — это **контракт схемы БД во времени**.

- `store/models.py` описывает **как схема должна выглядеть** (SQLAlchemy models).
- `store/migrations/versions/*.py` описывает **как перейти** от одной версии схемы к другой (история изменений).
- В самой БД хранится текущая версия схемы в таблице `alembic_version`.

Цель: любой разработчик/CI должен уметь поднять чистую SQLite БД командой:

```bash
alembic upgrade head
```

и получить схему, совместимую со `store` и `use_cases`.

---

## Строгие ограничения проекта

- Миграции — часть persistence → живут в `store/migrations`.
- Модели БД — только в `store/models.py`.
- Миграции **не импортируют** `core/`, `use_cases/`, `api/` (только `store.*`).
- SQLite: обязательно **batch mode** (`render_as_batch=True`).

---

## Структура файлов

### 1) `alembic.ini`
Главный конфиг Alembic.

Ключевое:
- `script_location = store/migrations`
- `sqlalchemy.url = sqlite:///data/app.db`

Это означает:
- Alembic ищет миграции в `store/migrations`
- По умолчанию применяет их к БД `data/app.db`

---

### 2) `store/migrations/env.py`
Точка входа Alembic.

Что важно:
- `target_metadata = Base.metadata` (берётся из `store.models`)
- включены сравнения для автогенерации:
  - `compare_type=True`
  - `compare_server_default=True`
- SQLite batch mode:
  - `render_as_batch=True`

`env.py` делает так, чтобы работало:

```bash
alembic revision --autogenerate -m "..."
```

---

### 3) `store/migrations/versions/*.py`
Файлы ревизий (миграций). Каждая миграция — это **дельта** (изменение) схемы.

Внутри:
- `revision` — идентификатор миграции
- `down_revision` — предыдущая миграция
- `upgrade()` — применить изменения
- `downgrade()` — откатить изменения

---

## Как Alembic понимает "какая версия у БД сейчас"

В базе есть таблица `alembic_version`, где хранится текущая ревизия (например `0001`).

Команды:

Показать текущую версию БД:
```bash
alembic current
```

Показать последнюю (head) версию в коде:
```bash
alembic heads
```

Норма:
- `current == head`

---

## Основные команды

### Применить миграции к БД
```bash
alembic upgrade head
```

### Откатить на 1 миграцию
```bash
alembic downgrade -1
```

### Посмотреть историю миграций
```bash
alembic history
```

---

## Правильный workflow (каждый день)

### 0) Всегда начинай с синхронизации БД
Перед автогенерацией миграции:

```bash
alembic upgrade head
```

Это критично.

---

### 1) Изменил схему в `store/models.py`
Например: добавил поле, индекс, constraint.

---

### 2) Сгенерировал новую миграцию (не init!)
```bash
alembic revision --autogenerate -m "add_<что_сделал>"
```

Примеры:
- `add_error_source`
- `index_errors_status`
- `alter_actions_nullable`

---

### 3) Проверил миграцию глазами
Открой новый файл в `store/migrations/versions/` и убедись:
- добавления/изменения ожидаемые
- нет неожиданных `drop_table` или удаления индексов

---

### 4) Применил миграцию и прогнал тесты
```bash
alembic upgrade head
pytest -q
```

---

## Особое правило: init делается один раз

Первая миграция (например `0001_init`) создаёт все таблицы.

⚠️ **Никогда не делай повторно:**
```bash
alembic revision --autogenerate -m "init"
```

Если `init` уже есть, а тебе нужна новая миграция — это всегда “дельта”, например `add_*`.

---

## Почему бывает ошибка "Target database is not up to date"

Эта ошибка появляется, когда ты запускаешь:

```bash
alembic revision --autogenerate ...
```

но база **не на head**.

Пример:
- В репозитории есть миграция `0001 (head)`
- БД пустая или на старой версии

Решение:
1) Привести БД к head:
   ```bash
   alembic upgrade head
   ```
2) Потом автогенерировать миграцию:
   ```bash
   alembic revision --autogenerate -m "add_x"
   ```

---

## SQLite и batch mode

SQLite ограниченно поддерживает `ALTER TABLE`.
Поэтому Alembic работает в режиме batch:

- создаёт временную таблицу новой схемы
- переносит данные
- удаляет старую
- переименовывает новую

Это включено через:

```py
render_as_batch=True
```

в `env.py` (offline и online режимы).

---

## Smoke test миграций

В проекте есть smoke test, который проверяет:

- на чистой SQLite БД
- `alembic upgrade head`
- все ожидаемые таблицы существуют

Запуск:
```bash
pytest -q
```

---

## Частые проблемы и быстрые решения

### 1) `alembic current` ничего не показывает
Обычно:
- ты смотришь на другую БД (другой `sqlalchemy.url`)
- или миграции ещё не применялись (нет `alembic_version`)

Решение:
```bash
alembic upgrade head
alembic current
```

---

### 2) Автогенерация предлагает "Detected added table ..." для всех таблиц
Это значит, что Alembic сравнивает модели с **пустой/другой БД**.

Проверь `sqlalchemy.url` в `alembic.ini` и что `data/app.db` — та самая БД.

---

### 3) Случайно создал второй init
Если сгенерировал лишний `*_init.py` — просто удали этот файл из `store/migrations/versions/`
и убедись, что `alembic heads` снова показывает один head.

---

## TL;DR

- `store/models.py` = желаемая схема
- `store/migrations/versions/` = история изменений
- `alembic_version` в БД = текущая версия

Всегда:
```bash
alembic upgrade head
alembic revision --autogenerate -m "add_x"
alembic upgrade head
pytest -q
```
