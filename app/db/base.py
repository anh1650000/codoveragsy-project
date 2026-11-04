"""Khai báo lớp gốc cho các model SQLAlchemy."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Lớp gốc để SQLAlchemy đăng ký các bảng."""
