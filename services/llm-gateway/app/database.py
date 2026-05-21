"""Database connection and session management."""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from .config import get_settings
from .models import Base


engine = None
async_session_maker = None


def get_engine():
    """Get database engine."""
    global engine
    if engine is None:
        settings = get_settings()
        engine = create_async_engine(
            settings.postgres_dsn,
            echo=settings.log_level == "DEBUG",
            pool_pre_ping=True,
        )
    return engine


def get_session_maker():
    """Get session maker."""
    global async_session_maker
    if async_session_maker is None:
        async_session_maker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return async_session_maker


async def get_db() -> AsyncSession:
    """Get database session dependency."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database tables."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
