"""Gọi model, xác thực JSON bằng Pydantic và thử lại lỗi cấu trúc có giới hạn."""

import json
import re
from collections.abc import Sequence

from openai import OpenAI
from pydantic import ValidationError

from app.extraction.schema import RawExtraction
from app.llm.client import get_llm_client, get_llm_model
from app.llm.prompts import build_extraction_messages


class ExtractionError(RuntimeError):
    """Lỗi trích xuất kèm các output thô để lưu phục vụ gỡ lỗi."""

    def __init__(self, message: str, raw_outputs: list[str]):
        super().__init__(message)
        self.raw_outputs = raw_outputs


def _clean_json_text(text: str) -> str:
    """Lọc bỏ các khối markdown ```json nếu mô hình trả về kèm định dạng."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def extract_fields(
    chunks: Sequence[dict[str, int | None | str]],
    client: OpenAI | None = None,
    model: str | None = None,
    max_retries: int = 2,
) -> tuple[RawExtraction, list[str]]:
    """Gọi LLM và xác thực JSON với Pydantic, hỗ trợ retry tối đa max_retries lần."""
    if max_retries < 0:
        raise ValueError("max_retries không được âm")
    llm_client = client or get_llm_client()
    llm_model = model or get_llm_model()
    raw_outputs: list[str] = []
    validation_error: str | None = None

    for attempt in range(max_retries + 1):
        response = llm_client.chat.completions.create(
            model=llm_model,
            messages=build_extraction_messages(chunks, validation_error),
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw_output = response.choices[0].message.content or ""
        raw_outputs.append(raw_output)
        try:
            cleaned = _clean_json_text(raw_output)
            parsed_json = json.loads(cleaned)
            return RawExtraction.model_validate(parsed_json), raw_outputs
        except (json.JSONDecodeError, ValidationError) as error:
            validation_error = str(error)
            if attempt == max_retries:
                break

    raise ExtractionError(
        f"Model không trả JSON đúng schema sau {max_retries + 1} lần gọi.",
        raw_outputs,
    )
