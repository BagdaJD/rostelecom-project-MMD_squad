# Экосистема коммерческого блока

Прототип аналитической системы для коммерческого блока ПАО «Ростелеком» — хакатон, осень 2026.
Каркас построен по ТЗ и архитектуре v2 (разделы 4–15); файл ТЗ в репозиторий не включён,
его нужно положить в `docs/` отдельным коммитом.

Три модуля поверх одного слоя данных: **Радар присутствия**, **Инвестиционный навигатор**, **Калькулятор сделок**.

## Стек

React + TypeScript + Vite · FastAPI + SQLAlchemy 2 + Alembic · PostgreSQL/PostGIS · Redis + RQ + APScheduler · scikit-learn / CatBoost.

## Структура

```
frontend/          React-приложение (src/app, pages, features, components, api, types, styles)
backend/
  app/             HTTP-слой: api, core (конфиг, безопасность), db, models, schemas,
                   services, repositories, workers
  modules/         бизнес-логика модулей: radar, investments, deals, auth, exports, notifications
  ingestion/       адаптеры источников, нормализация, матчинг, расписания, CLI
  ml/              признаки, скоринг, оценка качества, артефакты моделей
  alembic/         миграции
  tests/           pytest
infra/             Dockerfile-ы, reverse-proxy, скрипты инициализации
data/seed/         синтетический демо-набор (не реальные данные)
docs/              ТЗ, формат экспорта, источники, ограничения моделей
```

## Быстрый старт

```bash
cp .env.example .env            # заполнить SECRET_KEY и TOTP_ENCRYPTION_KEY
make up                         # postgres+postgis, redis, backend, worker, frontend
make db-init                    # первая миграция (autogenerate + upgrade)
make seed                       # загрузка демо-набора из data/seed
```

Без Docker, только бэкенд для разработки:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://rtk:rtk@localhost:5432/rtk
uvicorn app.main:app --reload     # http://localhost:8000/docs
pytest -q
```

Фронтенд: `cd frontend && npm install && npm run dev` (http://localhost:5173).

## Пользователь и 2FA

```bash
cd backend && python -m app.cli create-user --email a@example.com --role analyst
python -m app.cli enable-2fa --email a@example.com   # выведет secret для приложения-аутентификатора
```

## Что уже работает в каркасе

| Часть | Состояние |
|---|---|
| Модель данных, миграционный конвейер, слои api/service/repository | готовы к наполнению |
| Эвристический скоринг потенциала, «белые пятна», классификация потребностей, оценка по аналогам | реализованы как детерминированные функции, покрыты тестами |
| Импорт демо-набора, нормализация, дедупликация по ИНН/имени, provenance | реализованы |
| CSV/CRM и DOCX-экспорт | реализованы, формат CRM описан в `docs/export-mapping.md` |
| 2FA TOTP, роли, rate-limit входа, аудит | реализованы |
| Адаптеры ФНС / ЕИС | заглушки: доступ и лицензии согласуются отдельно (см. `docs/data-sources.md`) |
| Обучение CatBoost, дашборд маржинальности | не реализованы, см. раздел 3 ТЗ «вне скоупа» |

## Документация

- [`docs/export-mapping.md`](docs/export-mapping.md) — колонки CSV и маппинг в CRM
- [`docs/data-sources.md`](docs/data-sources.md) — источники, лицензии, ограничения доступа
- [`docs/model-limits.md`](docs/model-limits.md) — что обещают и чего не обещают модели

## Ограничения демо-режима

`data/seed/` — синтетические данные. Присутствие услуг Ростелекома, цены на оборудование и ПО и история сделок в демо-наборе смоделированы и помечены `is_synthetic`; в UI такие значения показываются с плашкой «демо».
