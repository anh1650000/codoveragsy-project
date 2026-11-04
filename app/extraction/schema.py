"""Schema Pydantic cho dữ liệu trích xuất thô từ hợp đồng."""

from pydantic import BaseModel, ConfigDict


class ExtractedField(BaseModel):
    """Giá trị trích xuất nguyên văn và câu nguồn; cả hai có thể vắng mặt."""

    model_config = ConfigDict(extra="forbid")

    value: str | None
    quote: str | None


class RawExtraction(BaseModel):
    """Các trường hợp đồng mà model phải trả về."""

    model_config = ConfigDict(extra="forbid")

    party_a_name: ExtractedField
    party_b_name: ExtractedField
    party_b_tax_code: ExtractedField
    party_b_legal_representative: ExtractedField
    contract_value: ExtractedField
    effective_date: ExtractedField
    payment_terms: ExtractedField
