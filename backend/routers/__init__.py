from backend.routers.auth import router as auth_router
from backend.routers.devices import router as devices_router
from backend.routers.terminal import router as terminal_router

__all__ = ["auth_router", "devices_router", "terminal_router"]
