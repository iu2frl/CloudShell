from backend.routers.audit import router as audit_router
from backend.routers.auth import router as auth_router
from backend.routers.auth_2fa import router as auth_2fa_router
from backend.routers.config_transfer import router as config_transfer_router
from backend.routers.devices import router as devices_router
from backend.routers.ftp import router as ftp_router
from backend.routers.keys import router as keys_router
from backend.routers.sftp import router as sftp_router
from backend.routers.terminal import router as terminal_router

__all__ = [
    "audit_router",
    "auth_router",
    "auth_2fa_router",
    "config_transfer_router",
    "devices_router",
    "ftp_router",
    "keys_router",
    "sftp_router",
    "terminal_router",
]
