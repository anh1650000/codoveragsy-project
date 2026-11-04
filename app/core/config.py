"""Đọc cấu hình môi trường cho các script và ứng dụng."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def get_setting(name: str, default: str | None = None) -> str | None:
    """Trả về biến môi trường sau khi nạp file .env ở gốc repo."""
    return os.getenv(name, default)
