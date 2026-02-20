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

```bash
make test   # runs backend integration tests locally
```

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
