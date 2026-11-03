# SellerDesk — единый интерфейс стенда. Порты: PostgreSQL 55101, API 8101, фронт 5101.
SHELL := /bin/bash

# Тесты чистят таблицы, поэтому по умолчанию у них своя база. Если DATABASE_URL задан
# в окружении (CI), тесты используют его.
ifdef DATABASE_URL
TEST_DATABASE_URL ?= $(DATABASE_URL)
else
TEST_DATABASE_URL ?= postgresql+psycopg://sellerdesk:sellerdesk@localhost:55101/sellerdesk_test
endif
DATABASE_URL ?= postgresql+psycopg://sellerdesk:sellerdesk@localhost:55101/sellerdesk
export DATABASE_URL

BACKEND := cd backend &&
FRONTEND := cd frontend &&
E2E := cd e2e &&

.PHONY: help install up down dev lint test test-backend test-frontend e2e audit openapi format

help:
	@grep -E '^[a-z-]+:' Makefile | cut -d: -f1 | tr '\n' ' '; echo

install:
	$(BACKEND) uv sync --frozen
	$(FRONTEND) npm ci
	$(E2E) npm ci && npx playwright install chromium

up:
	docker compose up --build

down:
	docker compose down -v

## Локально без Docker: миграции, сид, первая синхронизация, затем API и фронт.
dev:
	$(BACKEND) uv run python -m app.cli bootstrap
	trap 'kill 0' EXIT; \
	( $(BACKEND) uv run uvicorn app.main:app --host 127.0.0.1 --port 8101 --reload ) & \
	( $(FRONTEND) npm run dev ) & \
	wait

lint:
	$(BACKEND) uv run ruff check . && uv run ruff format --check . && uv run mypy app tests
	$(FRONTEND) npx eslint . && npx tsc -b --noEmit && npx prettier --check .
	$(E2E) npx tsc --noEmit

format:
	$(BACKEND) uv run ruff format . && uv run ruff check --fix .
	$(FRONTEND) npx prettier --write .

test: test-backend test-frontend

test-backend:
	$(BACKEND) DATABASE_URL=$(TEST_DATABASE_URL) uv run pytest --cov=app --cov-report=term

test-frontend:
	$(FRONTEND) npx vitest run

## Поднимает API и фронт сам (webServer в playwright.config.ts) или переиспользует запущенные.
e2e:
	$(E2E) npx playwright test

audit:
	$(BACKEND) uv run --with pip-audit pip-audit --skip-editable
	$(FRONTEND) npm audit --audit-level=high
	$(E2E) npm audit --audit-level=high

openapi:
	$(BACKEND) uv run python -m app.cli openapi
