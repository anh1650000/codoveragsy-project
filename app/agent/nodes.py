"""Các node xử lý và hàm nghiệp vụ thuần cho Contract Audit Agent."""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.agent.state import ContractAuditState
from app.core.config import get_setting
from app.extraction.extractor import extract_fields, extract_retry_fields
from app.extraction.schema import (
    REQUIRED_FIELDS,
    AuditItem,
    ExtractedField,
    FieldStatus,
    RawExtraction,
    VerifiedField,
)
from app.guardrails.citation_verifier import EXTRACTION_FIELD_NAMES, CitationVerifier
from app.parsing.document_parser import parse_document

# Hai trạng thái lỗi trích dẫn kích hoạt retry (và chuyển NEEDS_HUMAN_REVIEW nếu hết lượt).
FAILED_VERIFY_STATUSES: frozenset[FieldStatus] = frozenset(
    {FieldStatus.QUOTE_NOT_FOUND, FieldStatus.VALUE_NOT_IN_QUOTE}
)
DISCREPANCY_ERROR_TYPES: frozenset[str] = frozenset(
    {"ENTITY_NOT_FOUND", "IDENTITY_MISMATCH", "VALUE_OVER_LIMIT"}
)

ParserFn = Callable[[str | Path], list[dict]]
ExtractorFn = Callable[[Sequence[dict]], RawExtraction]
RetryExtractorFn = Callable[[Sequence[dict], Sequence[VerifiedField]], dict[str, ExtractedField]]
VerifierFn = Callable[[RawExtraction, Sequence[dict]], list[VerifiedField]]


def _parse_bool_setting(name: str, default: bool) -> bool:
    raw = get_setting(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int_setting(name: str, default: int) -> int:
    raw = get_setting(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"Cấu hình {name} không hợp lệ: {raw!r}") from error
    if value < 0:
        raise ValueError(f"Cấu hình {name} không được âm: {value}")
    return value


@dataclass(frozen=True)
class AgentConfig:
    """Cấu hình hành vi của graph đọc từ .env để phục vụ chạy thật và ablation."""

    enable_verifier: bool = True
    enable_retry: bool = True
    max_retries: int = 2

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """Đọc các cờ cấu hình từ biến môi trường / file .env."""
        return cls(
            enable_verifier=_parse_bool_setting("ENABLE_VERIFIER", True),
            enable_retry=_parse_bool_setting("ENABLE_RETRY", True),
            max_retries=_parse_int_setting("MAX_RETRIES", 2),
        )


def _make_trace_entry(node: str, summary: str, decision: str) -> dict[str, str]:
    """Tạo một bản ghi trace_log thống nhất theo mục 7 của AGENTS.md."""
    return {
        "node": node,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary,
        "decision": decision,
    }


def _default_extractor(chunks: Sequence[dict]) -> RawExtraction:
    raw_extraction, _ = extract_fields(chunks)
    return raw_extraction


def _default_retry_extractor(
    chunks: Sequence[dict],
    failed_fields: Sequence[VerifiedField],
) -> dict[str, ExtractedField]:
    retried, _ = extract_retry_fields(chunks, failed_fields)
    return retried


def _default_verifier(raw_extraction: RawExtraction, chunks: Sequence[dict]) -> list[VerifiedField]:
    return CitationVerifier().verify(raw_extraction, chunks)


def _bypass_verify(raw_extraction: RawExtraction) -> list[VerifiedField]:
    """Giả lập kết quả khi ENABLE_VERIFIER=false: mọi field có giá trị đều coi là VERIFIED."""
    # Mục đích phục vụ thí nghiệm ablation (Tuần 7): khi tắt verifier, mọi giá trị LLM sinh ra
    # (kể cả ảo giác) sẽ đi thẳng sang đối soát mà không kiểm quote, còn match_score/page/chunk_id
    # để None để phân biệt với field đã qua CitationVerifier thật.
    results: list[VerifiedField] = []
    for field_name in EXTRACTION_FIELD_NAMES:
        extracted: ExtractedField = getattr(raw_extraction, field_name)
        status = FieldStatus.VERIFIED if extracted.value is not None else FieldStatus.NOT_PRESENT
        results.append(
            VerifiedField(
                name=field_name,
                value=extracted.value,
                quote=extracted.quote,
                status=status,
                match_score=None,
                page=None,
                chunk_id=None,
            )
        )
    return results


def _format_status_summary(verified_fields: Sequence[VerifiedField]) -> str:
    counts = Counter(vf.status for vf in verified_fields)
    ordered_statuses = (
        FieldStatus.VERIFIED,
        FieldStatus.QUOTE_NOT_FOUND,
        FieldStatus.VALUE_NOT_IN_QUOTE,
        FieldStatus.NOT_PRESENT,
    )
    parts = [f"{counts[st]} {st.value}" for st in ordered_statuses if counts[st] > 0]
    return ", ".join(parts) if parts else "0 field"


def collect_review_items(verified_fields: Sequence[VerifiedField]) -> list[AuditItem]:
    """Tạo AuditItem(NEEDS_HUMAN_REVIEW) cho các trường cần người kiểm tra thủ công."""
    # Gom riêng bước này để tái sử dụng ở Tuần 5: những field chưa được xác thực (còn lỗi sau retry)
    # hoặc trường bắt buộc bị thiếu tuyệt đối không đưa vào đối soát DB tự động nhằm tránh kết luận sai.
    items: list[AuditItem] = []
    for vf in verified_fields:
        if vf.status in FAILED_VERIFY_STATUSES:
            items.append(
                AuditItem(
                    error_type="NEEDS_HUMAN_REVIEW",
                    field_name=vf.name,
                    extracted_value=vf.value,
                    expected_value=None,
                    detail=f"Trường '{vf.name}' chưa đạt kiểm chứng trích dẫn ({vf.status.value}), cần người kiểm tra.",
                )
            )
        elif vf.status == FieldStatus.NOT_PRESENT and vf.name in REQUIRED_FIELDS:
            items.append(
                AuditItem(
                    error_type="NEEDS_HUMAN_REVIEW",
                    field_name=vf.name,
                    extracted_value=None,
                    expected_value=None,
                    detail=f"Trường bắt buộc '{vf.name}' không có trong tài liệu (NOT_PRESENT), cần người kiểm tra.",
                )
            )
    return items


def determine_overall_result(audit_items: Sequence[AuditItem]) -> str:
    """Xác định kết luận tổng thể theo thứ tự ưu tiên ở mục 7 của AGENTS.md."""
    if any(item.error_type in DISCREPANCY_ERROR_TYPES for item in audit_items):
        return "DISCREPANCY_FOUND"
    if any(item.error_type == "NEEDS_HUMAN_REVIEW" for item in audit_items):
        return "NEEDS_REVIEW"
    return "CLEAN"


def build_nodes(
    *,
    parser: ParserFn | None = None,
    extractor: ExtractorFn | None = None,
    retry_extractor: RetryExtractorFn | None = None,
    verifier: VerifierFn | None = None,
    config: AgentConfig | None = None,
) -> dict[str, Callable[[ContractAuditState], dict]]:
    """Khởi tạo các node kèm dependency injection để test dễ thay bằng mock."""
    parse_fn = parser or parse_document
    extract_fn = extractor or _default_extractor
    retry_extract_fn = retry_extractor or _default_retry_extractor
    verify_fn = verifier or _default_verifier
    cfg = config or AgentConfig.from_env()

    def parse_node(state: ContractAuditState) -> dict:
        chunks = parse_fn(state["file_path"])
        file_name = Path(state["file_path"]).name
        return {
            "chunks": chunks,
            "trace_log": [
                _make_trace_entry(
                    node="parse_node",
                    summary=f"Đã tách {len(chunks)} chunks từ {file_name}",
                    decision="next: extract_node",
                )
            ],
        }

    def extract_node(state: ContractAuditState) -> dict:
        raw_extraction = extract_fn(state["chunks"])
        present_count = sum(
            1
            for name in EXTRACTION_FIELD_NAMES
            if getattr(raw_extraction, name).value is not None
        )
        return {
            "raw_extraction": raw_extraction,
            "trace_log": [
                _make_trace_entry(
                    node="extract_node",
                    summary=f"Trích xuất {present_count}/{len(EXTRACTION_FIELD_NAMES)} field có giá trị",
                    decision="next: verify_citation_node",
                )
            ],
        }

    def verify_citation_node(state: ContractAuditState) -> dict:
        raw_extraction = state.get("raw_extraction")
        if raw_extraction is None:
            raise RuntimeError("Thiếu raw_extraction trước khi chạy verify_citation_node.")

        if not cfg.enable_verifier:
            verified_fields = _bypass_verify(raw_extraction)
            return {
                "verified_fields": verified_fields,
                "trace_log": [
                    _make_trace_entry(
                        node="verify_citation_node",
                        summary=f"Bỏ qua verifier: {_format_status_summary(verified_fields)}",
                        decision="skip: ENABLE_VERIFIER=false -> reconcile_db_node",
                    )
                ],
            }

        verified_fields = verify_fn(raw_extraction, state["chunks"])
        failed_count = sum(1 for vf in verified_fields if vf.status in FAILED_VERIFY_STATUSES)
        retry_count = state.get("retry_count", 0)

        if failed_count == 0:
            decision = "tất cả hợp lệ -> reconcile_db_node"
        elif not cfg.enable_retry:
            decision = f"skip retry (ENABLE_RETRY=false): {failed_count} field lỗi -> reconcile_db_node"
        elif retry_count < cfg.max_retries:
            decision = f"retry: {failed_count} field lỗi"
        else:
            decision = f"hết lượt retry ({retry_count}/{cfg.max_retries}): {failed_count} field lỗi -> reconcile_db_node"

        return {
            "verified_fields": verified_fields,
            "trace_log": [
                _make_trace_entry(
                    node="verify_citation_node",
                    summary=_format_status_summary(verified_fields),
                    decision=decision,
                )
            ],
        }

    def retry_extraction_node(state: ContractAuditState) -> dict:
        raw_extraction = state.get("raw_extraction")
        if raw_extraction is None:
            raise RuntimeError("Thiếu raw_extraction trước khi chạy retry_extraction_node.")

        failed_fields = [
            vf for vf in state["verified_fields"] if vf.status in FAILED_VERIFY_STATUSES
        ]
        failed_names = {vf.name for vf in failed_fields}
        retried_fields = retry_extract_fn(state["chunks"], failed_fields)

        # Chỉ cập nhật đúng các field lỗi; giữ nguyên toàn bộ field đã VERIFIED hoặc NOT_PRESENT
        # để LLM không thể vô tình ghi đè kết quả đã kiểm chứng ở lượt trước.
        safe_updates = {
            name: field
            for name, field in retried_fields.items()
            if name in failed_names
        }
        merged_raw = raw_extraction.model_copy(update=safe_updates)
        new_retry_count = state.get("retry_count", 0) + 1

        return {
            "raw_extraction": merged_raw,
            "retry_count": new_retry_count,
            "trace_log": [
                _make_trace_entry(
                    node="retry_extraction_node",
                    summary=f"Yêu cầu lại {len(failed_fields)} field: {', '.join(vf.name for vf in failed_fields)}",
                    decision=f"retry_count={new_retry_count} -> verify_citation_node",
                )
            ],
        }

    def reconcile_db_node(state: ContractAuditState) -> dict:
        # Khung Tuần 4: chưa truy vấn PostgreSQL, chỉ gom các field NEEDS_HUMAN_REVIEW.
        # Tuần 5 sẽ giữ phần collect_review_items này và bổ sung đối soát các field VERIFIED với master_entities.
        audit_items = collect_review_items(state["verified_fields"])
        return {
            "audit_items": audit_items,
            "trace_log": [
                _make_trace_entry(
                    node="reconcile_db_node",
                    summary=f"Khung đối soát (chưa nối DB): {len(audit_items)} mục NEEDS_HUMAN_REVIEW",
                    decision="next: generate_report_node",
                )
            ],
        }

    def generate_report_node(state: ContractAuditState) -> dict:
        audit_items = state.get("audit_items", [])
        overall_result = determine_overall_result(audit_items)
        report = {
            "contract_id": state["contract_id"],
            "file_path": state["file_path"],
            "overall_result": overall_result,
            "fields": [vf.model_dump(mode="json") for vf in state.get("verified_fields", [])],
            "audit_items": [item.model_dump(mode="json") for item in audit_items],
            "retry_count": state.get("retry_count", 0),
        }
        return {
            "overall_result": overall_result,
            "report": report,
            "trace_log": [
                _make_trace_entry(
                    node="generate_report_node",
                    summary=f"overall_result={overall_result}, {len(audit_items)} cảnh báo",
                    decision="END",
                )
            ],
        }

    return {
        "parse_node": parse_node,
        "extract_node": extract_node,
        "verify_citation_node": verify_citation_node,
        "retry_extraction_node": retry_extraction_node,
        "reconcile_db_node": reconcile_db_node,
        "generate_report_node": generate_report_node,
    }
