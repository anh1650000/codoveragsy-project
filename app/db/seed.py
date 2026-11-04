"""Tạo bảng và nạp dữ liệu đối tác giả vào PostgreSQL."""

import asyncio

from sqlalchemy import select

from app.db.base import Base
from app.db.models import AuditLog, Contract, ContractEntity, MasterEntity  # noqa: F401
from app.db.seed_data import MASTER_ENTITIES
from app.db.session import AsyncSessionLocal, engine


async def seed_database() -> None:
    """Tạo schema rồi thêm/cập nhật các công ty mẫu theo mã số thuế."""
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        for item in MASTER_ENTITIES:
            entity = await session.scalar(
                select(MasterEntity).where(MasterEntity.vat_code == item["vat_code"])
            )
            if entity is None:
                session.add(MasterEntity(**item))
            else:
                for field, value in item.items():
                    setattr(entity, field, value)
        await session.commit()
    print(f"Đã tạo schema và seed {len(MASTER_ENTITIES)} công ty giả.")


async def main() -> None:
    """Đóng pool trong cùng event loop đã dùng để kết nối PostgreSQL."""
    try:
        await seed_database()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
