import os
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


# Import all models here so SQLAlchemy knows about them before create_all()
def _import_models():
    from backend.models import device, auth, audit  # noqa: F401
    _ = device, auth, audit


def get_engine():
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    return create_async_engine(
        f"sqlite+aiosqlite:///{settings.db_path}",
        echo=False,
    )


engine = get_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    """Create all tables on startup."""
    _import_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
