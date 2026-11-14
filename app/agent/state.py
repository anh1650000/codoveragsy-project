"""Định nghĩa state dùng chung cho các node trong LangGraph."""

import operator
from typing import Annotated, TypedDict

from app.extraction.schema import AuditItem, RawExtraction, VerifiedField


class ContractAuditState(TypedDict):
    """Trạng thái xuyên suốt một lần thẩm định hợp đồng theo mục 7 của AGENTS.md."""

    contract_id: int
    file_path: str
    chunks: list[dict]  # Mỗi chunk gồm {chunk_id, page, text}; DOCX có page = None.
    raw_extraction: RawExtraction | None
    verified_fields: list[VerifiedField]
    retry_count: int
    audit_items: list[AuditItem]
    overall_result: str | None
    report: dict | None
    # Dùng operator.add làm reducer để mỗi node chỉ cần trả về {"trace_log": [mục_mới]},
    # LangGraph tự nối dồn lịch sử thực thi qua mọi bước (kể cả các vòng lặp retry).
    trace_log: Annotated[list[dict], operator.add]
