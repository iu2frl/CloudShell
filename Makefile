.PHONY: help dev build up down logs restart shell test

COMPOSE = docker compose
IMAGE   = cloudshell

help:
	@echo "CloudShell — available targets:"
	@echo ""
	@echo "  make dev      Start backend + frontend dev servers (no Docker)"
	@echo "  make build    Build the Docker image"
	@echo "  make up       Start the stack with Docker Compose (detached)"
	@echo "  make down     Stop the stack"
	@echo "  make logs     Tail container logs"
	@echo "  make restart  Restart the container"
	@echo "  make shell    Open a shell inside the running container"
	@echo "  make test     Run backend integration tests locally"
	@echo ""

# ── Local development (no Docker) ─────────────────────────────────────────────

dev:
	@echo "Starting backend..."
	DATA_DIR=/tmp/cloudshell-dev SECRET_KEY=devsecret ADMIN_USER=admin ADMIN_PASSWORD=admin \
	  .venv/bin/python -m uvicorn backend.main:app --reload --port 8000 &
	@echo "Starting frontend dev server..."
	cd frontend && npm run dev

# ── Docker ────────────────────────────────────────────────────────────────────

build:
	docker build -t $(IMAGE) .

up:
	@if [ ! -f .env ]; then \
	  echo "No .env found — copying .env.example"; \
	  cp .env.example .env; \
	fi
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

restart:
	$(COMPOSE) restart

shell:
	$(COMPOSE) exec cloudshell /bin/bash

# ── Tests ─────────────────────────────────────────────────────────────────────

test:
	DATA_DIR=/tmp/cloudshell-test SECRET_KEY=ci-test-secret \
	  ADMIN_USER=admin ADMIN_PASSWORD=admin TOKEN_TTL_HOURS=1 \
	  .venv/bin/python -m pytest tests/ -v
