"""Một điểm truy cập dùng chung cho API tương thích OpenAI."""

from openai import OpenAI

from app.core.config import get_setting


def get_llm_model() -> str:
    """Trả về tên model đã cấu hình trong .env."""
    model = get_setting("LLM_MODEL", "frob/qwen3.5-instruct:4b")
    if not model:
        raise RuntimeError("Thiếu LLM_MODEL trong .env")
    return model


def get_llm_client() -> OpenAI:
    """Tạo client từ cấu hình để mọi script dùng cùng một endpoint."""
    base_url = get_setting("LLM_BASE_URL", "http://localhost:11434/v1")
    api_key = get_setting("LLM_API_KEY", "ollama")
    if not base_url:
        raise RuntimeError("Thiếu LLM_BASE_URL trong .env")
    return OpenAI(base_url=base_url, api_key=api_key or "ollama", timeout=300)



