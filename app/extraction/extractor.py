"""Gọi model, xác thực JSON bằng Pydantic và thử lại lỗi cấu trúc có giới hạn."""

import json
import re
from collections.abc import Sequence

from openai import OpenAI
from pydantic import ValidationError

from app.extraction.schema import ExtractedField, RawExtraction, VerifiedField
from app.llm.client import get_llm_client, get_llm_model
from app.llm.prompts import build_extraction_messages, build_retry_extraction_messages


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


def extract_retry_fields(
    chunks: Sequence[dict[str, int | None | str]],
    failed_fields: Sequence[VerifiedField],
    client: OpenAI | None = None,
    model: str | None = None,
    max_retries: int = 2,
) -> tuple[dict[str, ExtractedField], list[str]]:
    """Chỉ gọi LLM trích xuất lại các trường lỗi và validate từng trường bằng ExtractedField."""
    if max_retries < 0:
        raise ValueError("max_retries không được âm")
    if not failed_fields:
        return {}, []

    llm_client = client or get_llm_client()
    llm_model = model or get_llm_model()
    target_names = [field.name for field in failed_fields]
    raw_outputs: list[str] = []
    validation_error: str | None = None

    for attempt in range(max_retries + 1):
        response = llm_client.chat.completions.create(
            model=llm_model,
            messages=build_retry_extraction_messages(chunks, failed_fields, validation_error),
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw_output = response.choices[0].message.content or ""
        raw_outputs.append(raw_output)
        try:
            cleaned = _clean_json_text(raw_output)
            parsed_json = json.loads(cleaned)
            if not isinstance(parsed_json, dict):
                raise ValueError("Phản hồi retry phải là một JSON object.")
            missing = [name for name in target_names if name not in parsed_json]
            if missing:
                raise ValueError(f"Thiếu các trường cần retry: {', '.join(missing)}")

            validated: dict[str, ExtractedField] = {}
            for name in target_names:
                raw_field = parsed_json[name]
                if raw_field is None:
                    validated[name] = ExtractedField(value=None, quote=None)
                else:
                    validated[name] = ExtractedField.model_validate(raw_field)
            return validated, raw_outputs
        except (json.JSONDecodeError, ValidationError, ValueError) as error:
            validation_error = str(error)
            if attempt == max_retries:
                break

    raise ExtractionError(
        f"Model không trả JSON retry đúng schema sau {max_retries + 1} lần gọi.",
        raw_outputs,
    )
