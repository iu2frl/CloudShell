.PHONY: help dev build build-backend build-frontend smoke-test up down logs restart shell test test-unit test-coverage test-all

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
	@echo "  make smoke-test       Run the two-container Docker smoke test locally"
	@echo ""
	@echo "  make test             Run the full test suite (pytest + vitest + coverage)"
	@echo "  make test-unit        Run tests without coverage reporting (fast)"
	@echo "  make test-coverage    Run tests and open the HTML coverage report"
	@echo "  make test-all         Run tests for Python 3.11, 3.12, and 3.13"
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

smoke-test:
	bash scripts/smoke-test-docker.sh cloudshell-backend cloudshell-frontend

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

_TEST_ENV = DATA_DIR=/tmp/cloudshell-test-$$(date +%s) \
            SECRET_KEY=ci-test-secret \
            ADMIN_USER=admin \
            ADMIN_PASSWORD=admin \
            TOKEN_TTL_HOURS=1 \
            AUDIT_RETENTION_DAYS=7 \
            CORS_ORIGINS="*"

# Full suite: pytest + coverage + vitest (mirrors CI exactly)
test:
	mkdir -p reports
	$(_TEST_ENV) .venv/bin/python -m pytest
	cd frontend && npm test

# Fast run: no coverage instrumentation, no XML reports
test-unit:
	$(_TEST_ENV) .venv/bin/python -m pytest \
	  --no-cov --no-header -q
	cd frontend && npm test

# Full suite + open the HTML report in the default browser
test-coverage:
	mkdir -p reports
	$(_TEST_ENV) .venv/bin/python -m pytest
	@echo ""
	@echo "Opening HTML report..."
	@open reports/htmlcov/index.html 2>/dev/null \
	  || xdg-open reports/htmlcov/index.html 2>/dev/null \
	  || echo "HTML report is at reports/htmlcov/index.html"

# Matrix run across all supported Python versions (requires pyenv or similar)
test-all:
	@for py in python3.11 python3.12 python3.13; do \
	  if command -v $$py >/dev/null 2>&1; then \
	    echo ""; \
	    echo "=== $$py ==="; \
	    mkdir -p reports; \
	    $(_TEST_ENV) $$py -m pytest --no-header -q 2>&1 | tail -5; \
	  else \
	    echo "$$py not found, skipping"; \
	  fi; \
	done
