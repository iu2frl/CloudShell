.PHONY: help dev build build-backend build-frontend up down logs restart shell test

COMPOSE = docker compose

help:
	@echo "CloudShell -- available targets:"
	@echo ""
	@echo "  make dev              Start backend + frontend dev servers (no Docker)"
	@echo "  make build            Build both Docker images"
	@echo "  make build-backend    Build the backend image only"
	@echo "  make build-frontend   Build the frontend image only"
	@echo "  make up               Start the stack with Docker Compose (detached)"
	@echo "  make down             Stop the stack"
	@echo "  make logs             Tail container logs"
	@echo "  make restart          Restart all containers"
	@echo "  make shell            Open a shell inside the running backend container"
	@echo "  make test             Run backend integration tests locally"
	@echo ""

# ── Local development (no Docker) ─────────────────────────────────────────────

dev:
	@echo "Starting backend..."
	DATA_DIR=/tmp/cloudshell-dev SECRET_KEY=devsecret ADMIN_USER=admin ADMIN_PASSWORD=admin \
	  CORS_ORIGINS="http://localhost:5173" \
	  .venv/bin/python -m uvicorn backend.main:app --reload --port 8000 &
	@echo "Starting frontend dev server..."
	cd frontend && npm run dev

# ── Docker ────────────────────────────────────────────────────────────────────

build: build-backend build-frontend

build-backend:
	docker build -f Dockerfile.backend -t cloudshell-backend .

build-frontend:
	docker build -f Dockerfile.frontend -t cloudshell-frontend .

up:
	@if [ ! -f .env ]; then \
	  echo "No .env found -- copying .env.example"; \
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
	$(COMPOSE) exec backend /bin/bash

# ── Tests ─────────────────────────────────────────────────────────────────────

test:
	DATA_DIR=/tmp/cloudshell-test SECRET_KEY=ci-test-secret \
	  ADMIN_USER=admin ADMIN_PASSWORD=admin TOKEN_TTL_HOURS=1 \
	  CORS_ORIGINS="*" \
	  .venv/bin/python -m pytest tests/ -v
