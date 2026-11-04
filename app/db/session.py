"""Tạo engine và session bất đồng bộ cho PostgreSQL."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_setting

DATABASE_URL = get_setting(
    "DATABASE_URL",
    "postgresql+asyncpg://contracts:contracts@localhost:5432/contracts",
)
engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
