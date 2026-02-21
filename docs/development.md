# Development Setup

## Prerequisites

- Python 3.12+
- Node.js 18+

## Backend

```bash
cd CloudShell
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run with dev defaults
DATA_DIR=/tmp/cloudshell-dev SECRET_KEY=devsecret ADMIN_USER=admin ADMIN_PASSWORD=admin \
  uvicorn backend.main:app --reload --port 8000
```

API docs available at **<http://localhost:8000/docs>**

## Frontend

```bash
cd frontend
npm install
npm run dev   # Vite dev server on :5173, proxies /api → :8000
```

Open **<http://localhost:5173>**

## Build (production bundle)

```bash
cd frontend && npm run build   # output goes into the Nginx image via Dockerfile.frontend
```

## Running tests

Tests are written with **pytest** and **pytest-asyncio**.  Every test uses an
in-memory SQLite database and a mocked ASGI transport — no running server or
Docker daemon is required.

### Setup

Install the test dependencies inside the virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # includes pytest, pytest-asyncio, pytest-cov, httpx
```

### Make targets

| Target | What it does |
| --- | --- |
| `make test` | Full suite with coverage — mirrors CI exactly. Writes `reports/junit.xml`, `reports/coverage.xml`, and `reports/htmlcov/`. |
| `make test-unit` | Fast run without coverage instrumentation. Use this during active development. |
| `make test-coverage` | Full suite + automatically opens the HTML coverage report in your browser. |
| `make test-all` | Runs the suite under Python 3.11, 3.12, and 3.13 (skips versions not installed). |

```bash
make test            # recommended default
make test-unit       # faster, no coverage overhead
make test-coverage   # full run + open HTML report
```

### Running pytest directly

```bash
# Full suite (coverage on, matches pytest.ini defaults)
source .venv/bin/activate
DATA_DIR=/tmp/cloudshell-dev SECRET_KEY=devsecret \
  ADMIN_USER=admin ADMIN_PASSWORD=admin \
  python -m pytest

# Single file
python -m pytest tests/test_auth_api.py -v

# Single test
python -m pytest tests/test_auth_api.py::test_login_returns_token -v

# Skip coverage for a quick smoke-check
python -m pytest --no-cov -q
```

### Test layout

```text
tests/
  conftest.py               # shared fixtures: db_session, client, auth_client
  test_auth_api.py          # POST /auth/token, /refresh, /logout, /me, /change-password
  test_auth_internals.py    # boot-id mismatch, revoked tokens, credential edge-cases
  test_audit_api.py         # GET /audit/logs, POST /audit/prune
  test_audit_auth_flow.py   # audit entries written by auth endpoints
  test_audit_service.py     # write_audit, prune_old_entries, get_client_ip
  test_crypto_service.py    # encrypt/decrypt, key file helpers, generate_key_pair
  test_database.py          # _import_models, init_db, get_db
  test_devices_api.py       # full CRUD on /devices/
  test_devices_extended.py  # password/key update, key-file cleanup on delete
  test_keys_api.py          # POST /keys/generate
  test_main.py              # /api/health, global exception handler, BOOT_ID
  test_ssh_known_hosts.py   # _known_hosts_path, accept-new policy, stream_session
  test_ssh_service.py       # create_session, close_session, get_session_meta, _ws_error
  test_terminal_api.py      # POST /terminal/session/{id}, WS auth guard
```

### Coverage reports

After `make test` the following reports are written locally:

| Path | Format |
| --- | --- |
| `reports/htmlcov/index.html` | Interactive HTML — open in any browser |
| `reports/coverage.xml` | Cobertura XML — consumed by CI |
| `reports/junit.xml` | JUnit XML — consumed by CI |

These paths are listed in `.gitignore` and are never committed.

### CI integration

Every pull request and every push to `main` / `dev` runs the full suite via
`.github/workflows/ci.yml` → `.github/workflows/unit-tests.yml`.

What you see on each PR:

- **Checks tab** — a "Unit Test Results" check created by
  `EnricoMi/publish-unit-test-result-action` showing pass / fail counts and a
  per-test breakdown.
- **PR comment** — the same action posts (and updates) a comment with a
  pass/fail table on every run.
- **Job summary** — the "Run pytest with coverage" step writes the full
  `coverage report` table and a line/branch coverage summary table directly
  into the GitHub Actions job summary page.
- **Artifacts** — `junit-results-py3.12` and `coverage-report-py3.12` are
  uploaded for 30 days and can be downloaded from the Actions run page.  The
  `coverage-report` artifact contains the full HTML report.

## Docker workflow

```bash
make build            # build both Docker images
make build-backend    # build the backend image only
make build-frontend   # build the frontend image only
make up               # build images + start stack (copies .env.example if no .env exists)
make down             # stop the stack
make logs             # tail container logs
make restart          # restart all containers
make shell            # open a shell inside the running backend container
make smoke-test       # run the two-container Docker smoke test locally
make dev              # start backend + frontend dev servers locally (no Docker)
```

Or use Docker Compose directly:

```bash
docker compose up -d          # start
docker compose logs -f        # tail logs
docker compose down           # stop
docker compose down -v        # stop + delete data volume
```
