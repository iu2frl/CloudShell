#!/usr/bin/env bash
# scripts/smoke-test-docker.sh
# Spins up the two-container stack locally and verifies:
#   1. Backend becomes healthy
#   2. Frontend becomes healthy
#   3. Nginx correctly proxies /api/health to the backend
#
# Usage: bash scripts/smoke-test-docker.sh [backend-image] [frontend-image]
#   Defaults: cloudshell-backend:ci  cloudshell-frontend:ci
set -euo pipefail

BACKEND_IMAGE="${1:-cloudshell-backend:ci}"
FRONTEND_IMAGE="${2:-cloudshell-frontend:ci}"
NETWORK="cloudshell-ci-internal"
BACKEND_CONTAINER="cs-backend-ci"
FRONTEND_CONTAINER="cs-frontend-ci"

cleanup() {
    echo "Cleaning up..."
    docker stop "$BACKEND_CONTAINER" "$FRONTEND_CONTAINER" 2>/dev/null || true
    docker rm   "$BACKEND_CONTAINER" "$FRONTEND_CONTAINER" 2>/dev/null || true
    docker network rm "$NETWORK" 2>/dev/null || true
}
trap cleanup EXIT

# ── Network ────────────────────────────────────────────────────────────────────
docker network create "$NETWORK" 2>/dev/null || true

# ── Start backend ──────────────────────────────────────────────────────────────
docker run -d \
    --name "$BACKEND_CONTAINER" \
    --network "$NETWORK" \
    --network-alias backend \
    -e SECRET_KEY=ci-test-secret \
    -e ADMIN_USER=admin \
    -e ADMIN_PASSWORD=admin \
    "$BACKEND_IMAGE"

# ── Start frontend ─────────────────────────────────────────────────────────────
docker run -d \
    --name "$FRONTEND_CONTAINER" \
    --network "$NETWORK" \
    -p 8080:80 \
    "$FRONTEND_IMAGE"

# ── Wait for backend ───────────────────────────────────────────────────────────
echo "Waiting for backend to be healthy..."
for i in $(seq 1 30); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$BACKEND_CONTAINER" 2>/dev/null || echo "starting")
    echo "  [$i] backend=$STATUS"
    [ "$STATUS" = "healthy" ] && break
    sleep 2
done

# ── Wait for frontend ──────────────────────────────────────────────────────────
echo "Waiting for frontend to be healthy..."
for i in $(seq 1 20); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$FRONTEND_CONTAINER" 2>/dev/null || echo "starting")
    echo "  [$i] frontend=$STATUS"
    [ "$STATUS" = "healthy" ] && break
    sleep 2
done

# ── Collect final statuses ─────────────────────────────────────────────────────
BACKEND_STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$BACKEND_CONTAINER")
FRONTEND_STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$FRONTEND_CONTAINER")

echo "Final backend status : $BACKEND_STATUS"
echo "Final frontend status: $FRONTEND_STATUS"

# ── Verify Nginx proxies the API ───────────────────────────────────────────────
HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/health)
echo "Proxied /api/health HTTP status: $HTTP"

# ── Assert ─────────────────────────────────────────────────────────────────────
FAIL=0
[ "$BACKEND_STATUS"  = "healthy" ] || { echo "FAIL: backend never became healthy";  FAIL=1; }
[ "$FRONTEND_STATUS" = "healthy" ] || { echo "FAIL: frontend never became healthy"; FAIL=1; }
[ "$HTTP"            = "200"     ] || { echo "FAIL: Nginx proxy returned HTTP $HTTP instead of 200"; FAIL=1; }

[ "$FAIL" = "0" ] && echo "Docker smoke test passed" || exit 1
