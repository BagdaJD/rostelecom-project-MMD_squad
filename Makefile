.PHONY: help up down logs ps build db-init db-migrate seed seed-calculator user test test-backend test-frontend typecheck lint worker demo

help:
	@echo "up            — поднять весь стек (postgres+postgis, redis, api, worker, web)"
	@echo "down          — остановить стек"
	@echo "db-migrate    — применить миграции"
	@echo "db-revision   — создать миграцию autogenerate (m='название')"
	@echo "seed          — загрузить демонстрационный набор"
	@echo "demo          — пересоздать data/seed/demo_bundle.json"
	@echo "seed-calculator — таблицы и данные калькулятора сделок (модуль 3)"
	@echo "user          — make user email=me@example.com: пользователь + секрет 2FA"
	@echo "test          — тесты backend и frontend"
	@echo "typecheck     — tsc --noEmit"

# Пути в docker-compose.yml заданы от папки infra (../backend, ../.env), поэтому она —
# каталог проекта; .env берётся из корня репозитория.
COMPOSE := docker compose -f infra/docker/docker-compose.yml --project-directory infra --env-file "$(CURDIR)/.env"

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) ps

build:
	$(COMPOSE) build

db-init: db-migrate seed

db-migrate:
	$(COMPOSE) exec backend alembic upgrade head

db-revision:
	$(COMPOSE) exec backend alembic revision --autogenerate -m "$(m)"

seed:
	$(COMPOSE) exec backend python -m app.cli seed --bundle ../data/seed/demo_bundle.json

demo:
	python3 infra/scripts/make_demo_bundle.py

seed-calculator:  ## калькулятор сделок: таблицы calc_* (и недостающие остальные) + данные кейса
	$(COMPOSE) exec backend python -m modules.deal_calculator.seed --create-all

user:  ## make user email=me@example.com [role=manager] — спросит пароль, покажет секрет 2FA
	$(COMPOSE) exec backend python -m app.cli create-user --email $(email) --role $(or $(role),manager)
	$(COMPOSE) exec backend python -m app.cli enable-2fa --email $(email)

worker:
	$(COMPOSE) up -d worker

test: test-backend test-frontend

test-backend:
	cd backend && .venv/bin/python -m pytest -q

test-frontend:
	cd frontend && npm run test -- --passWithNoTests

typecheck:
	cd frontend && npm run typecheck

lint:
	cd backend && .venv/bin/python -m ruff check app modules ingestion ml tests
