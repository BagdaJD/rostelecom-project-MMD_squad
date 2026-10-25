# Передача backend на сервер

PostgreSQL/PostGIS и Redis команда настраивает непосредственно на сервере.
Локальная установка на Windows для передачи кода не требуется.
Код проверен локально: 154 переносимых теста прошли; реальные интеграционные проверки
и приёмка выполняются после настройки серверного окружения.

## Состав запуска

Для backend нужны Python 3.12, PostgreSQL с PostGIS, Redis и два процесса:

- API: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`;
- worker с расписанием: `python -m app.workers.main`.

Оба процесса запускаются из `backend/`, одним окружением Python и с одинаковыми `.env`
и каталогом экспортов. На сервер передаётся весь репозиторий: `backend/`, `data/case/`,
`data/seed/`, `infra/`. Файлы `data/case/` нужны также каталогу калькулятора.
Фронтенд, PostgreSQL и Redis не запускаются внутри процесса FastAPI.

## Вариант без Docker

Команды ниже рассчитаны на Linux-сервер с уже доступными PostgreSQL/PostGIS и Redis.
Из корня репозитория:

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install -c backend/constraints.txt -e backend
cp .env.example .env
```

В `.env` замените значения:

| Переменная | Значение на сервере |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://USER:PASSWORD@HOST:5432/DB`; специальные символы логина/пароля кодируются для URL |
| `REDIS_URL` | Адрес настроенного Redis, например `redis://127.0.0.1:6379/0` |
| `SECRET_KEY`, `TOTP_ENCRYPTION_KEY` | Два разных случайных постоянных секрета, одинаковых у API/worker/init |
| `APP_ENV` | `production` для HTTPS; для отдельной демонстрации по HTTP — `dev` |
| `CORS_ORIGINS` | JSON-массив адресов браузерного frontend, например `["https://project.example.org"]` |
| `DATA_MODE` | `case` |
| `EXPORT_DIR` | Один доступный на запись каталог для API и worker; при одном cwd подходит `exports` |

По умолчанию шаблон `.env.example` содержит Docker-имена хостов `postgres` и `redis`.
При обычном запуске замените их на реальные адреса. При `APP_ENV=production` refresh
cookie имеет `Secure` и требует HTTPS; иначе браузер не сможет обновлять сессию.
Пароль аккаунта задаётся при создании пользователя, `DEFAULT_PASSWORD` его не создаёт.

Под администратором PostgreSQL создайте БД, пользователя и расширение PostGIS в этой БД.
Миграционному пользователю нужны права на схему и создание/обновление materialized view.
Затем из `backend/` выполните:

```bash
.venv/bin/python -m app.cli check-config
.venv/bin/python -m app.cli check-services
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m app.cli bootstrap-data
.venv/bin/python -m modules.deal_calculator.seed
.venv/bin/python -m app.cli refresh-views
.venv/bin/python -m app.cli create-user --email manager@example.com --role manager
```

Пароль вводится интерактивно. Второй фактор пользователь настроит при первом входе;
при необходимости можно подготовить его через `app.cli enable-2fa --email ...`.
Пользователя создают один раз. Повторные загрузки данных допускаются, миграции
применяются перед запуском новой версии. Для старой БД без истории Alembic сначала
нужна сверка схемы; автоматический `stamp` не предусмотрен.

В двух процессах из `backend/`:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv/bin/python -m app.workers.main
```

Эти команды задаются менеджеру процессов сервера как два отдельных сервиса; у обоих
`WorkingDirectory` должен указывать на `backend/`. API на `127.0.0.1:8000` доступен
локальному reverse proxy; внешний домен, HTTPS и публикацию порта настраивает команда
сервера. API поддерживает `--host 0.0.0.0`, если размещение требует прямого доступа.

## Если на сервере используется Docker

В корне репозитория подготовьте `.env`, затем:

```bash
docker compose -f infra/docker/docker-compose.yml --env-file .env up --build --wait
docker compose -f infra/docker/docker-compose.yml --env-file .env exec backend \
  python -m app.cli create-user --email manager@example.com --role manager
```

Compose поднимает PostgreSQL/PostGIS и Redis, выполняет миграции/импорт/подготовку
витрин отдельным `init`, запускает API и worker. В этом варианте адреса БД/Redis
внутри Compose задаются самим стеком. Для уже существующих внешних БД/Redis используйте
обычный Python-запуск выше либо отдельную конфигурацию Compose под эти сервисы.
Текущий Compose рассчитан на поставляемые им БД и Redis.

## Приёмка после запуска

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/api/v1/ready
```

Readiness должен вернуть `status=ready`, `database=ok`, `schema=ok`, `redis=ok`,
`seeded=true`. `/health` проверяет только процесс и сам по себе не подтверждает
готовность backend. Swagger расположен по `/docs`.

Проверить с пользовательским access token после 2FA:

1. Список компаний, карточку, карту, список/карточку проекта и таймлайн.
2. Проект → черновик калькулятора → расчёт → утверждение менеджером → DOCX.
3. `POST /exports` → опрос `status_url` → `done` → скачивание CSV. Worker забирает
   новые запросы раз в минуту, поэтому сразу после POST состояние `pending` нормально.
4. Подписку и новое событие импорта → уведомление. Подписка не рассылает старые проекты.
5. Изоляцию: чужой расчёт/файл недоступен; analyst не утверждает цену.
6. Время ответа карты, фильтров и карточек относительно требования 2 секунд.

Контракты: [MFA и доступ](auth-and-access.md), [данные кейса](case-data-api.md),
[фильтры, события и фоновые задачи](background-and-run.md).

## Интеграционные тесты

Прогон выполняется на отдельной свежей тестовой БД и отдельном Redis DB/инстансе.
Ряд существовавших тестов загружает синтетический набор в общую схему; рабочая БД
для этого не используется. Задайте тестовые `DATABASE_URL`, `REDIS_URL` переменными
процесса, затем из `backend/`:

```bash
.venv/bin/python -m pip install -c constraints.txt -e '.[dev]'
export REQUIRE_INTEGRATION=1
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic check
.venv/bin/python -m pytest
```

Это включает все 21 проверки PostGIS/Redis вместо пропуска при отсутствии сервисов.
При Docker есть отдельный тестовый стек:

```bash
docker compose -p telecom-backend-test -f infra/docker/docker-compose.test.yml \
  up --build --abort-on-container-exit --exit-code-from tests tests
docker compose -p telecom-backend-test -f infra/docker/docker-compose.test.yml down
```

Серверная приёмка выполняется после настройки целевого окружения. Локальные
154 успешных теста не заменяют проверку миграций, MV и worker на сервере.
