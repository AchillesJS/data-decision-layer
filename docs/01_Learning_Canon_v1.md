0) Определение

Learning Canon DDW — это набор объектов, сигналов и правил, по которым DDW имеет право делать инженерные утверждения о:

достаточности данных

приближении к потолку

узком месте (data/model/noise/optimization)

ожидаемой отдаче от следующего шага

DDW не даёт “истину”.
DDW даёт оценку диапазоном + уверенность + доказательства.

1) Канонические вопросы (единственные, на которые DDW “отвечает”)

DDW отвечает только на:

Ceiling: каков вероятный потолок при текущем режиме? (диапазон)

Sufficiency: имеет ли смысл собирать ещё данные? (marginal gain)

Bottleneck: что вероятнее ограничивает рост?

Next experiment design: какие 1–3 запуска уменьшат неопределённость больше всего?

Любые “советы” — это производное от этих 4 вещей.

2) Канонические объекты (первичные сущности Learning-оси)
2.1 Run (запуск)

Run — атом наблюдения.

Минимальные поля (MVP):

id

dataset_id (или dataset_version)

dataset_size (N)

model_tag (строка)

seed

budget (одна шкала: steps или epochs или wall_time_sec)

metric_name (например, accuracy / wer / f1)

metric_final (число 0..1 или нормированное)

status (succeeded/failed)

started_at, finished_at

Опционально (но желательно):

metric_series (points: step→value) для train/val

config_hash, git_commit

notes, artifact_refs

2.2 MetricSeries

Ряд для run:

split: train/val/test

x_axis: step/epoch/time

points: [(x, y)]

валидации: x строго возрастает, y в допустимом диапазоне

2.3 LearningCurve (агрегированная кривая)

Набор Runs, приведённый к оси:

y = metric_final

x = dataset_size или x = budget

группировка по: model_tag + dataset_version + task

LearningCurve = не “график”. Это объект, который имеет:

набор точек

качество покрытия

оценку шума/variance

2.4 LearningModel (модель кривой)

Функция, которая аппроксимирует LearningCurve.

MVP модель:

power law / log fit (простая регрессия)

оценка качества фита (R²/MAE + sanity checks)

bootstrap для диапазонов (не байес!)

2.5 SaturationEstimate (оценка насыщения)

Структура вывода:

ceiling_range: [low, high]

marginal_gain_at_x_plus: диапазон прироста при +p% данных

confidence: low/med/high (или 0..1)

coverage: сколько точек, какой диапазон x

fit_quality: ok/weak/bad

assumptions: список

evidence_run_ids: ссылки

2.6 Regime (режим ограничения)

Классы (MVP):

DATA_LIMITED

MODEL_LIMITED

NOISE_LIMITED

OPTIMIZATION_LIMITED

UNKNOWN

Regime всегда возвращается как:

regime

confidence

evidence_signals[]

2.7 DataPotential (контейнер вывода) — уже в Core

В Learning Canon DataPotential = “упакованный вывод”:

range 0..1 (как ты и зафиксировал)

confidence

assumptions

limiting_factors (regime)

evidence (run_ids/links)

3) Канонические сигналы (что DDW измеряет)
3.1 Saturation / slope

производная улучшения по x (данные/бюджет)

если slope низкий и стабилен → плато вероятно

3.2 Variance / instability

разброс metric_final при одинаковом x (разные seed)

если variance высокий → выводы слабее, regime часто UNKNOWN/NOISE

3.3 Generalization gap (если есть series)

train выше val и gap растёт → переобучение/шум/нехватка данных

3.4 Fit quality

модель кривой не должна “объяснять” шум

если fit плохой → ceiling_range расширяется, confidence падает

4) Канонические правила честности (release-gate)
Rule H1: Никаких точечных потолков

Только диапазон. Всегда.

Rule H2: Нельзя выдавать regime, если нет минимального покрытия

Минимум для non-UNKNOWN:

≥ 3 точки по x и

хотя бы 1 повтор (seed) на одной из точек или

стабильная series-динамика

Иначе: UNKNOWN + “нужно 1–2 запуска”.

Rule H3: Любой вывод должен ссылаться на evidence_run_ids

Если нет ссылок → вывод запрещён.

Rule H4: Confidence обязателен и ограничивает UI

Если confidence низкий:

UI должен показывать “нужно больше экспериментов”

Auto Hypothesis может только “draft разведки”, без сильных формулировок

5) MVP-алгоритмы (без магии)
5.1 Fit (dataset_size → metric_final)

берём точки (x, y)

пробуем 2 модели: log и power

выбираем по MAE + sanity checks (монотонность, ceiling≤1)

bootstrap (например 200 ресэмплов) → интервалы

5.2 Ceiling range

из fitted curve → limit/асимптота или y на “большом x”

если модель не устойчива → диапазон расширяем

5.3 Marginal gain при +p%

gain = f(x*(1+p)) − f(x)

тоже диапазоном из bootstrap

5.4 Regime heuristics (MVP)

если slope высок и стабилен → DATA_LIMITED

если slope низок, fit хороший, variance низкий → MODEL_LIMITED

если variance высокий и/или gap нестабилен → NOISE_LIMITED

если series показывает нестабильность обучения (скачки/дивергенции) → OPTIMIZATION_LIMITED

иначе → UNKNOWN

6) Output контракты

Learning Engine возвращает только:

SaturationEstimate

RegimeEstimate

DataPotentialDraft

Никаких “делайте X”.

7) Связь с Auto Hypothesis

Auto Hypothesis разрешён только как:

генератор draft гипотез

вход: только объекты из Learning Engine (Regime, Saturation, Potential)

выход: statement + evidence + uncertainty + test plan (1–2 запуска)

сохранение: только после Accept человеком