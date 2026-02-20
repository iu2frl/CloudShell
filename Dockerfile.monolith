# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS frontend-build

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --silent

COPY frontend/ ./
RUN DOCKER_BUILD=1 npm run build


# ── Stage 2: Python backend ────────────────────────────────────────────────────
FROM python:3.12-slim AS final

LABEL org.opencontainers.image.title="CloudShell" \
      org.opencontainers.image.description="Self-hosted web SSH gateway" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/youruser/CloudShell"

# System deps for asyncssh / cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Run as non-root user
RUN groupadd --gid 1001 appgroup \
    && useradd --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend into the place FastAPI will serve it from
COPY --from=frontend-build /app/frontend/dist ./backend/static/

# Data directory — will be overridden by a volume in production
RUN mkdir -p /data/keys && chmod 700 /data/keys && chown -R appuser:appgroup /data /app

USER appuser

ENV DATA_DIR=/data \
    SECRET_KEY=changeme \
    ADMIN_USER=admin \
    ADMIN_PASSWORD=changeme \
    TOKEN_TTL_HOURS=8

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
