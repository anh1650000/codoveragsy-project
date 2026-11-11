"""Schema Pydantic cho dữ liệu trích xuất thô từ hợp đồng."""

from pydantic import BaseModel, ConfigDict


"""Schema Pydantic cho dữ liệu trích xuất thô từ hợp đồng."""

from pydantic import BaseModel, ConfigDict, field_validator
from enum import Enum


class ExtractedField(BaseModel):
    """Giá trị trích xuất nguyên văn và câu trích dẫn nguồn; cả hai có thể là None nếu tài liệu không có."""

    model_config = ConfigDict(extra="ignore")

    value: str | None = None
    quote: str | None = None

    @field_validator("value", "quote", mode="before")
    @classmethod
    def coerce_to_str(cls, v: object) -> str | None:
        """Ép kiểu số thành chuỗi để giữ nguyên văn bản nếu model trả về dạng số."""
        if v is None:
            return None
        return str(v)


class RawExtraction(BaseModel):
    """Bảy trường thông tin bắt buộc mà mô hình LLM phải trích xuất."""

    model_config = ConfigDict(extra="ignore")

    party_a_name: ExtractedField
    party_b_name: ExtractedField
    party_b_tax_code: ExtractedField
    party_b_legal_representative: ExtractedField
    contract_value: ExtractedField
    effective_date: ExtractedField
    payment_terms: ExtractedField

    @field_validator(
        "party_a_name",
        "party_b_name",
        "party_b_tax_code",
        "party_b_legal_representative",
        "contract_value",
        "effective_date",
        "payment_terms",
        mode="before",
    )
    @classmethod
    def coerce_field(cls, v: object) -> dict[str, str | None] | object:
        """Chuyển đổi linh hoạt nếu LLM trả về null thay vì object {value: null, quote: null}."""
        if v is None:
            return {"value": None, "quote": None}
        return v


class FieldStatus(str, Enum):
    """Trạng thái kiểm chứng trích dẫn bằng code cho từng trường."""

    VERIFIED = "VERIFIED"
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    VALUE_NOT_IN_QUOTE = "VALUE_NOT_IN_QUOTE"
    NOT_PRESENT = "NOT_PRESENT"


class VerifiedField(BaseModel):
    """Kết quả đầu ra của CitationVerifier cho một trường thông tin."""

    name: str
    value: str | None
    quote: str | None
    status: FieldStatus
    match_score: float | None
    page: int | None
    chunk_id: int | None
