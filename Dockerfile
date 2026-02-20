# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --silent

COPY frontend/ ./
RUN npm run build


# ── Stage 2: Python backend ────────────────────────────────────────────────────
FROM python:3.12-slim AS final

# System deps for asyncssh / cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend into the place FastAPI will serve it from
COPY --from=frontend-build /app/frontend/dist ./backend/static/

# Data directory (override with a volume)
RUN mkdir -p /data/keys && chmod 700 /data/keys

ENV DATA_DIR=/data \
    SECRET_KEY=changeme \
    ADMIN_USER=admin \
    ADMIN_PASSWORD=changeme \
    TOKEN_TTL_HOURS=8

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
