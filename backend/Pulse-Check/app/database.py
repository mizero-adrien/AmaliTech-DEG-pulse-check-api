import logging
import os

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

load_dotenv()

logger = logging.getLogger(__name__)

_raw_url = os.getenv(
    "DATABASE_URL",
    "postgresql://pulse_user:pulse_pass@localhost:5433/pulse_check_db",
)

# App uses asyncpg (non-blocking I/O); Alembic uses psycopg2 (sync)
ASYNC_DATABASE_URL = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
SYNC_DATABASE_URL = _raw_url.replace("postgresql+asyncpg://", "postgresql://", 1)

engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_pre_ping=True,  # Recycle stale connections automatically
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep attribute values accessible after commit
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
