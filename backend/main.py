import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import get_settings
from backend.database import init_db
from backend.routers import auth_router, devices_router, keys_router, terminal_router

VERSION = os.getenv("APP_VERSION", "dev")

# Configure application logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: [%(name)s] %(message)s",
)

log = logging.getLogger(__name__)
_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    settings = get_settings()
    os.makedirs(settings.data_dir, exist_ok=True)
    os.makedirs(settings.keys_dir, exist_ok=True)
    await init_db()
    log.info("CloudShell %s started (data_dir=%s)", VERSION, settings.data_dir)
    yield
    # Shutdown
    log.info("CloudShell shutting down")


app = FastAPI(
    title="CloudShell",
    description="Self-hosted web SSH gateway",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# ── API routes ────────────────────────────────────────────────────────────────

app.include_router(auth_router, prefix="/api")
app.include_router(devices_router, prefix="/api")
app.include_router(keys_router, prefix="/api")
app.include_router(terminal_router, prefix="/api")


@app.get("/api/health")
async def health():
    uptime_s = int(time.time() - _start_time)
    return {
        "status": "ok",
        "version": VERSION,
        "uptime_seconds": uptime_s,
    }
