# Отчёт интеграции

## Ветки

- Основа: `origin/dev-frontend-merge-backend`.
- Объединённая ветка: `origin/feature/ml-stage2-validation`.
- Результат: `integration/ml-frontend-backend`.
- Исходные ветки не изменялись. Конфликты разрешались вручную; массовый выбор `ours`/`theirs` не применялся.

## Разрешённые конфликты

Git сообщил о конфликтах `add/add` в 67 путях:

- Репозиторий и конфигурация: `.env.example`, `.github/workflows/ci.yml`, `.gitignore`, `Makefile`, `README.md`.
- Alembic: `backend/alembic.ini`, `backend/alembic/env.py`.
- Backend API: `backend/app/api/v1/api.py`, `backend/app/api/v1/endpoints/auth.py`, `backend/app/api/v1/endpoints/deals.py`, `backend/app/api/v1/endpoints/exports.py`, `backend/app/api/v1/endpoints/investments.py`, `backend/app/api/v1/endpoints/notifications.py`, `backend/app/api/v1/endpoints/radar.py`, `backend/app/cli.py`.
- Backend core, база и модели: `backend/app/core/config.py`, `backend/app/core/deps.py`, `backend/app/core/ratelimit.py`, `backend/app/core/security.py`, `backend/app/db/session.py`, `backend/app/main.py`, `backend/app/models/__init__.py`, `backend/app/models/account.py`, `backend/app/models/deal.py`, `backend/app/models/investment.py`, `backend/app/models/reference.py`, `backend/app/schemas/__init__.py`, `backend/app/workers/jobs.py`, `backend/app/workers/main.py`.
- Ingestion и ML: `backend/ingestion/loader.py`, `backend/ingestion/normalize.py`, `backend/ingestion/sources/__init__.py`, `backend/ml/deal_estimator.py`, `backend/ml/needs.py`, `backend/ml/scoring.py`.
- Сервисы, зависимости и backend-тесты: `backend/modules/auth/service.py`, `backend/modules/deals/service.py`, `backend/modules/investments/service.py`, `backend/modules/notifications/service.py`, `backend/modules/radar/service.py`, `backend/pyproject.toml`, `backend/tests/conftest.py`, `backend/tests/test_ingestion_integration.py`, `backend/tests/test_ml.py`, `backend/tests/test_normalize.py`, `backend/tests/test_security.py`.
- Документация: `docs/data-sources.md`, `docs/export-mapping.md`, `docs/model-limits.md`.
- Frontend: `frontend/package-lock.json`, `frontend/package.json`, `frontend/src/api/client.ts`, `frontend/src/app/App.tsx`, `frontend/src/app/main.tsx`, `frontend/src/components/states.tsx`, `frontend/src/features/radar/MapView.tsx`, `frontend/src/pages/CalculatorPage.tsx`, `frontend/src/pages/DashboardPage.tsx`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/NavigatorPage.tsx`, `frontend/src/pages/RadarPage.tsx`, `frontend/src/styles/global.css`, `frontend/src/types/api.ts`, `frontend/src/vite-env.d.ts`, `frontend/vite.config.ts`.
- Инфраструктура: `infra/docker/backend.Dockerfile`, `infra/docker/docker-compose.yml`.

В конфликтах backend сохранены auth/API и интеграционные поверхности dev-ветки; в итог включены ingestion, ML scoring/NLP и тесты ML-ветки. Также были вручную согласованы frontend-контракты и обработка nullable-значений.

## Изменения и контракты

- Добавлена Alembic merge revision `20261025_merge_ml_backend`, объединяющая application- и ML-истории без удаления миграций. `alembic heads` показывает один head. Миграции индексов и nullable-score подготовлены для offline SQL-режима; downgrade с проверкой данных остаётся online-проверкой.
- Ingestion сохраняет проверки идентификаторов и provenance, а обновление `client_status` не затирает состояние некорректными совпадениями. Radar использует сохранённые company/territory scoring snapshots, когда это применимо, и live-расчёт как fallback.
- Frontend типы heatmap отражают nullable `revenue_sum`, `growth_share` и `presence_score`. Карта не создаёт фиктивную точку без координат, а отсутствие presence не превращается в нулевой score.
- Рекомендации `ProjectNeed` сохраняют explicit/inferred metadata; `probability=null` не интерпретируется как 0%. Сериализация scoring snapshot согласована с backend-ответом.
- Экспорт калькулятора переведён на поддерживаемый `GET /calculator/estimates/{id}/csv`.
- API client согласован с MFA setup/response, credentials cookies и CSRF header для refresh/logout; Login показывает provisioning URI при первоначальной настройке 2FA.

## Проверки

- Backend `python -m ruff check .`: пройдено.
- Backend `python -m pytest -q`: один сбой в `tests/test_background_features.py::test_filters_subscription_start_and_inactive_users_are_respected` из-за `UNIQUE constraint failed: app_user.email`. В тестовом helper email строится из timestamp; повтор этого теста отдельно прошёл. Тесты не отключались и не исправлялись в рамках интеграции.
- Frontend `npm run build`: пройдено; Vite сообщает о chunk `maplibre-gl` больше 500 KB.
- Frontend `npm run typecheck`: пройдено.
- Frontend `npm run test`: 7 файлов, 69 тестов пройдены.
- Локальный smoke test: `/health` вернул HTTP 200; OpenAPI вернул 49 маршрутов, включая radar/score; Vite вернул HTTP 200.
- Readiness endpoint вернул `not_ready`: PostgreSQL и Redis недоступны в окружении. PostgreSQL/PostGIS интеграционные проверки и миграции на БД поэтому не запускались; production/shared DB не изменялась.
- Проверены один Alembic head, отсутствие неразрешённых путей и conflict markers. Сгенерированные build/dependency-файлы не включены в изменения.
- `npm ci` сообщал о 10 audit advisories (5 moderate, 2 high, 3 critical); зависимости в рамках интеграции не менялись, отдельный аудит не проводился.

## Ограничения и дальнейшие шаги

Интеграция прошла frontend build/typecheck/tests и локальную проверку liveness/OpenAPI, однако полный backend suite не зелёный из-за указанной коллизии тестовых email. До merge в `dev` следует стабилизировать генерацию уникального email в тестовом helper и повторить полный backend suite. Также нужны PostgreSQL/PostGIS/Redis в изолированном тестовом окружении для миграционного и readiness smoke-теста; отдельно следует разобрать npm audit advisories.
