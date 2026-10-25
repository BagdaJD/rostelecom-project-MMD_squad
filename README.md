# Экосистема коммерческого блока

Прототип аналитической системы для коммерческого блока ПАО «Ростелеком» — хакатон, осень 2026.
Продукт — веб-приложение: менеджер работает в браузере на компьютере или телефоне.
Telegram-бот и отдельное устанавливаемое приложение в MVP не входят.

Три модуля поверх одного слоя данных: **Радар присутствия**, **Инвестиционный навигатор**, **Калькулятор сделок**.

## Стек

React + TypeScript + Vite · FastAPI + SQLAlchemy 2 + Alembic · PostgreSQL/PostGIS · Redis + RQ + APScheduler · scikit-learn / CatBoost.

## Структура

```
frontend/          React-приложение (src/app, pages, features, components, api, types, styles)
backend/
  app/             HTTP-слой: api, core (конфиг, безопасность), db, models, schemas,
                   services, repositories, workers
  modules/         radar, investments, deal_calculator, прежний deals, auth, exports, notifications
  ingestion/       адаптеры источников, нормализация, матчинг, расписания, CLI
  ml/              признаки, скоринг, оценка качества, артефакты моделей
  alembic/         миграции
  tests/           pytest
infra/             Dockerfile-ы, reverse-proxy, скрипты инициализации
data/seed/         синтетический демо-набор (не реальные данные)
data/case/         исходный Excel кейса и подготовленный каталог калькулятора
docs/              ТЗ, формат экспорта, источники, ограничения моделей
```

## Быстрый старт

Нужны Docker с работающим Linux-движком и Docker Compose v2. В Windows Docker Desktop
требует включённого WSL 2. Команды выполняются из корня репозитория.

PowerShell, только backend:

```powershell
.\infra\scripts\dev.ps1 up
.\infra\scripts\dev.ps1 user -Email analyst@example.com -Role analyst
```

Скрипт создаёт `.env` со случайными локальными ключами, собирает backend, поднимает
PostgreSQL/PostGIS и Redis, применяет миграции, загружает компании и проекты кейса,
каталог калькулятора с демонстрационной историей и запускает
API с worker. Секреты TOTP и резервные коды из команды `user` сохраните в аутентификаторе.
Документация API: <http://localhost:8000/docs>. Для запуска frontend добавьте `-Web` к `up`.

Без PowerShell, например в Linux:

```bash
cp .env.example .env  # заменить SECRET_KEY и TOTP_ENCRYPTION_KEY случайными значениями
docker compose -f infra/docker/docker-compose.yml --env-file .env up --build --wait
# frontend по желанию: добавить --profile web перед up
```

Схема создаётся **миграциями Alembic**, а не генерацией миграций при каждом запуске
и не `create_all`. По умолчанию `DATA_MODE=case`: импортируются 759 компаний и 63 проекта
из Excel. Ещё 60 записей компаний создаются для отсутствующих в реестре инициаторов,
без выдуманного ИНН. Выручка и присутствие в книге отсутствуют и остаются неизвестными.
Новый калькулятор использует каталог кейса и синтетическую историю.
Для отдельной демонстрационной БД можно выбрать `DATA_MODE=demo` до первого запуска.
Переключение режима не удаляет уже загруженные данные; используйте отдельную БД/том.

Остановка, логи и изолированные тесты с PostgreSQL/PostGIS и Redis:

```powershell
.\infra\scripts\dev.ps1 status
.\infra\scripts\dev.ps1 logs
.\infra\scripts\dev.ps1 test
.\infra\scripts\dev.ps1 down
```

`test` использует отдельный Compose-проект и временную БД, не подключает данные рабочего
стека. `down` сохраняет рабочие тома. Повторный `up` применяет миграции и повторяет seed.
Проверка конфигурации без запущенного движка: `docker compose -f infra/docker/docker-compose.yml --env-file .env config --quiet`.

Локальная Python-разработка (PostgreSQL/PostGIS и Redis должны быть доступны отдельно):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -c constraints.txt -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://rtk:rtk@localhost:5432/rtk
alembic upgrade head
python -m app.cli bootstrap-data
python -m modules.deal_calculator.seed
python -m app.cli refresh-views
uvicorn app.main:app --reload     # http://localhost:8000/docs
```

Для Windows используйте интерпретатор настроенного окружения PyCharm и переменные
окружения PowerShell. Конфигурация читается из корневого `.env`, затем из `backend/.env`;
переменные процесса имеют приоритет. `CASE_WORKBOOK_PATH` задаёт книгу кейса,
`DEMO_BUNDLE_PATH` — синтетический seed. Для адресного повторного импорта:
`python -m app.cli import-case --workbook ../data/case/case_data_2026.xlsx`.

Без Docker в Windows можно использовать `infra/scripts/native.ps1`: `check`, `init`,
затем `api` и `worker` в двух терминалах. PostgreSQL/PostGIS и Redis должны быть
доступны по адресам из `.env`. Пошаговая инструкция, новые API и результаты проверок:
[background-and-run.md](docs/background-and-run.md).

Без БД можно выполнить `python -m pytest -m "not integration"`. Полный CI поднимает
PostGIS и Redis, применяет миграции, проверяет отсутствие расхождений схемы и запускает
все тесты с `REQUIRE_INTEGRATION=1`: недоступная БД считается ошибкой.

Frontend отдельно: `cd frontend && npm install && npm run dev` (http://localhost:5173).

## Пользователь и 2FA

```bash
cd backend && python -m app.cli create-user --email a@example.com --role analyst
python -m app.cli enable-2fa --email a@example.com   # выведет secret для приложения-аутентификатора
```

Второй фактор обязателен. Без предварительного CLI provisioning пользователь может
настроить аутентификатор через login → 2fa/setup → 2fa/verify; до подтверждения доступ
закрыт. Refresh хранится в HttpOnly cookie, обновление/выход требуют CSRF-заголовка.
Подробные ответы API, роли и изменения для frontend: [auth-and-access.md](docs/auth-and-access.md).

## Что уже работает в каркасе

| Часть | Состояние |
|---|---|
| Модель данных и миграции | пять ревизий, 43 таблицы и три materialized view, включая MFA, серверные сессии и фоновые задачи |
| Эвристический скоринг потенциала, «белые пятна», классификация потребностей, оценка по аналогам | реализованы как детерминированные функции, покрыты тестами |
| Импорт кейса и демо, нормализация, дедупликация по ИНН/имени, provenance | реализованы; повторный импорт и изменение исходной строки проверены |
| Карточки и справочники | компании, метрики, проекты, milestones, потребности, источники, регионы и отрасли |
| Радар | единый отчётный год, выбор источника без дублей, стабильный скоринг при фильтрации, муниципальные срезы |
| CSV/CRM и DOCX-экспорт | компании, навигатор и калькулятор; до 5000 строк синхронно, большие CSV — фоновая задача со статусом и защищённым скачиванием |
| Фильтры и сигналы | личные сохранённые фильтры и основной фильтр; наблюдения реестра/регионов с доказательством |
| Worker и уведомления | журнал событий, частоты подписок, квитанции и дедупликация, повторы и восстановление экспортов |
| Витрины и модель | готовые карта/белые пятна/таймлайн; обучение калькулятора в seed/worker, проверка актуальности артефакта |
| 2FA, сессии, роли и аудит | обязательный TOTP, однократные коды/ротация, cookie/CSRF, отзыв сессий, владение расчётами, роли и admin-аудит; интеграция клиента описана отдельно |
| Адаптеры ФНС / ЕИС | заглушки: доступ и лицензии согласуются отдельно (см. `docs/data-sources.md`) |
| Новый калькулятор `/api/v1/calculator` | себестоимость по каталогу, вилка, модельная маржа, аналоги, утверждение и КП; история синтетическая |

## Документация

Для знакомства с прототипом начните со [сценария демонстрации](docs/hackathon-demo.md).
Переносимый backend-набор: **154 успешных теста**. Для серверной приёмки предусмотрена
21 дополнительная интеграционная проверка PostgreSQL/PostGIS и Redis.

- [`docs/backend-foundation.md`](docs/backend-foundation.md) — схема данных, миграции и проверка запуска
- [`docs/hackathon-demo.md`](docs/hackathon-demo.md) — сценарий для проверки прототипа, возможности и ограничения
- [`docs/case-data-api.md`](docs/case-data-api.md) — импорт Excel, API и изменения контрактов для frontend
- [`docs/auth-and-access.md`](docs/auth-and-access.md) — обязательная 2FA, cookie/CSRF, роли и аудит
- [`docs/background-and-run.md`](docs/background-and-run.md) — фоновые задачи, фильтры/сигналы, новые API и запуск без Docker
- [`docs/server-deployment.md`](docs/server-deployment.md) — передача backend на сервер, инициализация, API/worker и приёмка
- [`docs/BACKEND_ROADMAP.md`](docs/BACKEND_ROADMAP.md) — схема проекта, аудит веток и план доработки
- [`docs/instructions.pdf`](docs/instructions.pdf) — исходное ТЗ v2.0
- [`docs/export-mapping.md`](docs/export-mapping.md) — колонки CSV и маппинг в CRM
- [`docs/data-sources.md`](docs/data-sources.md) — источники, лицензии, ограничения доступа
- [`docs/model-limits.md`](docs/model-limits.md) — что обещают и чего не обещают модели

## Ограничения демо-режима

`data/seed/` — синтетические данные. Присутствие услуг Ростелекома, цены на оборудование и ПО и история сделок в демо-наборе смоделированы и помечены `is_synthetic`; в UI такие значения показываются с плашкой «демо».
