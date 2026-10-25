# Data Pipeline, NLP и Scoring

Начните с [короткой проверки](../../docs/ml-quick-check.md).
Актуальный второй этап: [ml-stage2-report.md](../../docs/ml-stage2-report.md).

Полная инструкция: [docs/ml-pipeline.md](../../docs/ml-pipeline.md).
Результаты проверок: [docs/ml-evaluation.md](../../docs/ml-evaluation.md).
Исходный аудит: [docs/ml-audit.md](../../docs/ml-audit.md).

После установки `pip install -e ".[dev]"` из `backend/`:

```powershell
python -m ingestion.cli run --excel 'C:\Users\timof\Downloads\Хакатон_2026_фактура.xlsx' --output ml/artifacts/baseline --as-of 2026-10-24
pytest -q -ra
```

Нормализованные записи содержат сведения ИП. Они сохраняются локально в уже
игнорируемом `backend/ml/artifacts/`; в Git добавлены только агрегаты качества.
Ни одна команда `run`, `excel`, `fns`, `nlp`, `score` не подключается к БД.
Для записи в существующую PostgreSQL предусмотрена отдельная команда `import-db`.
