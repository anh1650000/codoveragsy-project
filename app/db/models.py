"""Các bảng PostgreSQL trong đặc tả dự án."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MasterEntity(Base):
    __tablename__ = "master_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vat_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_representative: Mapped[str | None] = mapped_column(String(255))
    max_contract_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Contract(Base):
    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="UPLOADED")
    overall_result: Mapped[str | None] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(Text)
    trace_log: Mapped[dict | list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    entities: Mapped[list["ContractEntity"]] = relationship(back_populates="contract", cascade="all, delete-orphan")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="contract", cascade="all, delete-orphan")


class ContractEntity(Base):
    __tablename__ = "contract_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    fields: Mapped[dict | list] = mapped_column(JSONB, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    contract: Mapped[Contract] = relationship(back_populates="entities")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    error_type: Mapped[str] = mapped_column(String(30), nullable=False)
    field_name: Mapped[str | None] = mapped_column(String(50))
    extracted_value: Mapped[str | None] = mapped_column(Text)
    expected_value: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    contract: Mapped[Contract] = relationship(back_populates="audit_logs")
