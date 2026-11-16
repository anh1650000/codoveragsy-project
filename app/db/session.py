"""Tạo engine và session bất đồng bộ cho PostgreSQL."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_setting

DATABASE_URL = get_setting(
    "DATABASE_URL",
    "postgresql+asyncpg://contracts:contracts@localhost:5432/contracts",
)
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

_active_session_maker = AsyncSessionLocal


def get_session_factory() -> async_sessionmaker:
    """Trả về sessionmaker đang hoạt động (cho phép ghi đè trong test môi trường riêng)."""
    return _active_session_maker


def set_session_factory(maker: async_sessionmaker) -> None:
    """Ghi đè sessionmaker (dùng trong test để trỏ vào database test riêng biệt)."""
    global _active_session_maker
    _active_session_maker = maker
