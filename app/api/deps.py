"""Dependency injection cho FastAPI: quản lý AsyncSession theo từng request."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Cung cấp AsyncSession cho mỗi request HTTP và tự động đóng/rollback khi có lỗi."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
