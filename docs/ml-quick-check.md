# Как проверить работу ML-части

Команды ниже — PowerShell из корня репозитория. Для первой установки нужен Python 3.12:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e './backend[dev]'
```

Обработка реального Excel без сервера, БД, Docker и embeddings:

```powershell
.\.venv\Scripts\python.exe -m ingestion.cli run --excel 'C:\Users\timof\Downloads\Хакатон_2026_фактура.xlsx' --output backend/ml/artifacts/demo --as-of 2026-10-25
$q = Get-Content backend/ml/artifacts/demo/quality.json -Raw -Encoding UTF8 | ConvertFrom-Json
$q | Select-Object companies,projects,valid_inn_percent,duplicate_inn_rows
$q.nlp
$q.company_scores
```

Ожидаются 759 компаний, 63 проекта, 100% валидных ИНН, 126 отраслевых рекомендаций,
13 проектов без рекомендаций. Score — эвристический приоритет, качество limited.
Это технические результаты; точность рекомендаций ещё не измерена экспертами.

Посмотреть рекомендации для первых трёх проектов:

```powershell
$data = Get-Content backend/ml/artifacts/demo/normalized.json -Raw -Encoding UTF8 | ConvertFrom-Json
$data.projects | Select-Object -First 3 title,@{Name='recommendations';Expression={($_.recommendations.need_category -join ', ')}}
```

У каждой записи в `recommendations` есть evidence_type, reason, evidence и версия.
Для inferred evidence=NULL, probability=NULL. Нормализованные персональные записи
сохраняются только локально в игнорируемых artifacts.

Быстрые unit/regression-тесты:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q -m 'not integration'
```

При незаданных MMD_EXCEL_PATH/MMD_E5_MODEL_PATH соответствующие проверки внешних
файлов явно пропускаются. Для проверки исходного файла:

```powershell
$env:MMD_EXCEL_PATH='C:\Users\timof\Downloads\Хакатон_2026_фактура.xlsx'
.\.venv\Scripts\python.exe -m pytest backend/tests/test_real_excel.py -q
```

Независимая оценка: локальные XLSX подготовлены в
`backend/ml/artifacts/stage2/expert-review/expert-review.xlsx` и `blind-review.xlsx`.
Все 63 проекта включены; экспертные поля пусты. Ключ `blind-key.json` не передавать
эксперту слепой версии. Генерация и импорт оценок:

```powershell
.\.venv\Scripts\python.exe -m ml.review --baseline backend/ml/artifacts/baseline/normalized.json --hybrid backend/ml/artifacts/hybrid/normalized.json --output backend/ml/artifacts/review
.\.venv\Scripts\python.exe -m ml.review --baseline backend/ml/artifacts/baseline/normalized.json --hybrid backend/ml/artifacts/hybrid/normalized.json --completed backend/ml/artifacts/review/expert-review.xlsx --output backend/ml/artifacts/review/evaluation.json
```

Перед генерацией должен быть выполнен baseline/hybrid прогон из
[полной инструкции](ml-pipeline.md). Совпадающие рекомендации объединяются;
ручная оценка одной идентичной рекомендации применяется к обоим методам.

Эксперт заполняет только поля оценки, сохраняя исходные строки и split:

- На листе Projects — `expert_explicit_categories` как JSON-массив IDs категорий
  и `explicit_evidence_json` как объект «категория → точная цитата». Включаются
  и явные категории, которые пропустили оба метода; `[]` означает проверенное
  отсутствие явных потребностей, пустая ячейка — ещё не проверено.
- Для inferred-рекомендаций — `expert_relevance`: `релевантно`, `нерелевантно`
  или `неясно`. Автоматическое заполнение по ответу модели недопустимо.
- Для слепой таблицы оценщик не получает blind-key.json; организатор передаёт
  этот файл evaluator через `--blind-key` после завершения ручной оценки.

Для проверки API с настоящей PostgreSQL/PostGIS нужны отдельная marker-защищённая
БД и применённая схема; команды описаны в [отчёте этапа 2](ml-stage2-report.md).
Не задавайте рабочую/общую БД для тестов. Удобнее сначала проверить CLI и JSON,
затем SQL/API отдельно; запуск frontend относится к другой части команды.
