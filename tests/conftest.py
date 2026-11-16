"""Cấu hình fixture dùng chung cho kiểm thử, bảo đảm KHÔNG đụng vào database dev."""

from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import MasterEntity
from app.db.seed_data import MASTER_ENTITIES
from app.db.session import (
    get_session_factory,
    set_session_factory,
)

# Cho phép SQLite biên dịch kiểu JSONB của PostgreSQL thành JSON trong môi trường test cô lập
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture(autouse=True)
def isolated_test_db(monkeypatch, tmp_path):
    """Tạo database test hoàn toàn riêng biệt trong bộ nhớ, tự động dọn dẹp sau mỗi test.
    
    Bảo đảm tuyệt đối:
    1. Không ghi, sửa hay xóa bất kỳ dòng nào trong database dev 'contracts'.
    2. Nạp sẵn 10 bản ghi master_entities để phục vụ đối soát.
    3. Trỏ session factory của ứng dụng sang database test trong suốt quá trình chạy test.
    """
    # Dùng SQLite in-memory với StaticPool để chia sẻ cùng một database giữa các luồng/task
    test_db_url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def _setup_and_seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            for item in MASTER_ENTITIES:
                entity = MasterEntity(
                    vat_code=item["vat_code"],
                    company_name=item["company_name"],
                    legal_representative=item.get("legal_representative"),
                    max_contract_value=Decimal(str(item["max_contract_value"]))
                    if item.get("max_contract_value") is not None
                    else None,
                )
                session.add(entity)
            await session.commit()
        return maker

    import asyncio
    maker = asyncio.run(_setup_and_seed())

    original_factory = get_session_factory()
    set_session_factory(maker)

    # Đặt thư mục upload tạm cho test
    test_upload_dir = tmp_path / "uploads"
    test_upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("UPLOAD_DIR", str(test_upload_dir))

    yield maker

    # Khôi phục trạng thái ban đầu sau khi test kết thúc
    set_session_factory(original_factory)
    asyncio.run(engine.dispose())
