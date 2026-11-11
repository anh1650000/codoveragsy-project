"""Kiểm chứng trích dẫn và kiểm tra value-in-quote hoàn toàn bằng code thuần."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.core.config import get_setting
from app.extraction.schema import ExtractedField, FieldStatus, RawExtraction, VerifiedField
from app.guardrails.normalizers import (
    EntityType,
    classify_entity_by_tax_code,
    extract_money_candidates,
    extract_vn_date_candidates,
    normalize_company_name,
    normalize_person_name,
    normalize_tax_code,
    normalize_text,
    parse_money,
    parse_vn_date,
)

# Thứ tự chuẩn của 7 trường trích xuất giúp đầu ra VerifiedField luôn ổn định khi lưu và hiển thị.
EXTRACTION_FIELD_NAMES: tuple[str, ...] = (
    "party_a_name",
    "party_b_name",
    "party_b_tax_code",
    "party_b_legal_representative",
    "contract_value",
    "effective_date",
    "payment_terms",
)

_TAX_OR_ID_GROUP_RE = re.compile(
    r"\b\d{3,4}(?:\s+\d{3,4}){2,3}\b|\d+(?:\s*-\s*\d{3}\b)?"
)


@dataclass(frozen=True)
class ChunkSpan:
    """Ánh xạ khoảng ký tự [start, end) trên chuỗi toàn văn chuẩn hóa về chunk và trang gốc."""

    start: int
    end: int
    chunk_id: int
    page: int | None


@dataclass(frozen=True)
class IndexedDocument:
    """Tài liệu toàn văn đã chuẩn hóa kèm bảng offset để tính vị trí bằng code."""

    full_text: str
    spans: list[ChunkSpan]


def _load_default_threshold() -> float:
    """Đọc CITATION_THRESHOLD từ cấu hình (.env) để giữ một nguồn ngưỡng duy nhất."""
    raw = get_setting("CITATION_THRESHOLD", "85")
    try:
        return float(raw) if raw is not None else 85.0
    except ValueError as error:
        raise ValueError(f"CITATION_THRESHOLD không hợp lệ: {raw!r}") from error


def _build_indexed_document(chunks: Sequence[dict]) -> IndexedDocument:
    """Chuẩn hóa từng chunk, ghép thành chuỗi toàn văn và dựng bảng offset tương ứng."""
    parts: list[str] = []
    spans: list[ChunkSpan] = []
    cursor = 0

    for chunk in chunks:
        norm_chunk = normalize_text(str(chunk.get("text") or ""))
        # Bỏ qua chunk rỗng sau chuẩn hóa để tránh chèn khoảng trắng thừa làm lệch offset.
        if not norm_chunk:
            continue
        if parts:
            parts.append(" ")
            cursor += 1
        start = cursor
        end = start + len(norm_chunk)
        parts.append(norm_chunk)
        spans.append(
            ChunkSpan(
                start=start,
                end=end,
                chunk_id=int(chunk["chunk_id"]),
                page=chunk.get("page"),
            )
        )
        cursor = end

    return IndexedDocument(full_text="".join(parts), spans=spans)


def _expand_to_token_boundaries(full_text: str, start: int, end: int) -> tuple[int, int]:
    """Khôi phục trọn từ/số nếu vị trí khớp của rapidfuzz cắt ngang giữa một token."""
    # partial_ratio_alignment căn theo độ dài quote của LLM; nếu quote bị thiếu dấu câu (vd thiếu ':')
    # thì dest_end có thể cắt hụt chữ số/ký tự cuối. Chỉ nới qua ký tự không phải khoảng trắng để không
    # vô tình kéo thêm từ hay con số từ câu kế bên vào vùng kiểm tra value-in-quote.
    while start > 0 and start < end and not full_text[start].isspace() and not full_text[start - 1].isspace():
        start -= 1
    while end > start and end < len(full_text) and not full_text[end - 1].isspace() and not full_text[end].isspace():
        end += 1
    return start, end


def _locate_chunk(span_start: int, spans: Sequence[ChunkSpan]) -> tuple[int | None, int | None]:
    """Suy ra chunk_id và page từ vị trí bắt đầu đoạn khớp trong chuỗi toàn văn."""
    # Quy ước quote vắt qua hai chunk (Lựa chọn 1): lấy chunk chứa vị trí bắt đầu (span_start)
    # và lấy số trang theo chunk đó. Lý do: giữ nguyên schema VerifiedField (chunk_id: int | None,
    # page: int | None) theo mục 6 của AGENTS.md, đồng thời trỏ đúng tới điểm bắt đầu trích dẫn.
    for span in spans:
        if span.start <= span_start < span.end:
            return span.chunk_id, span.page
    # Nếu vị trí bắt đầu rơi đúng vào dấu cách nối giữa hai chunk thì lấy chunk ngay sau nó.
    for span in spans:
        if span.end > span_start:
            return span.chunk_id, span.page
    return None, None


def _find_quote_match(norm_quote: str, full_text: str) -> tuple[float, int, int]:
    """Tìm vị trí đoạn văn bản gốc khớp nhất với quote đã chuẩn hóa."""
    if not norm_quote or not full_text:
        return 0.0, 0, 0

    # partial_ratio có tính đối xứng: nếu quote bịa dài hơn cả văn bản ngắn thì nó lại tìm văn bản
    # bên trong quote và trả 100 điểm. Dùng ratio toàn chuỗi khi quote dài hơn văn bản để chặn lỗi này.
    if len(norm_quote) > len(full_text):
        return float(fuzz.ratio(norm_quote, full_text)), 0, len(full_text)

    alignment = fuzz.partial_ratio_alignment(norm_quote, full_text)
    if alignment is None:
        return 0.0, 0, 0
    start, end = _expand_to_token_boundaries(full_text, alignment.dest_start, alignment.dest_end)
    return float(alignment.score), start, end


def _is_value_in_matched_text(
    field_name: str,
    value: str,
    matched_text: str,
    threshold: float,
    party_b_entity_type: EntityType = EntityType.UNKNOWN,
) -> bool:
    """Kiểm tra giá trị có thực sự nằm trong đoạn văn gốc tại vị trí khớp hay không."""
    if field_name == "contract_value":
        expected_money = parse_money(value)
        if expected_money is None:
            return False
        return expected_money in extract_money_candidates(matched_text)

    if field_name == "effective_date":
        expected_date = parse_vn_date(value)
        if expected_date is None:
            return False
        return expected_date in extract_vn_date_candidates(matched_text)

    if field_name == "party_b_tax_code":
        tax_digits = normalize_tax_code(value)
        if not tax_digits:
            return False
        # Trích các cụm mã số trong đoạn khớp rồi chuẩn hóa từng cụm để phân biệt đúng
        # MST công ty 10/13 số với CCCD cá nhân 12 số (tránh 10 số đầu khớp nhầm CCCD 12 số).
        matched_codes = {
            normalize_tax_code(token)
            for token in _TAX_OR_ID_GROUP_RE.findall(matched_text)
        }
        return tax_digits in matched_codes

    if field_name == "party_a_name":
        norm_value = normalize_company_name(value)
        if not norm_value:
            return False
        return norm_value in normalize_company_name(matched_text)

    if field_name == "party_b_name":
        # Nếu MST/CCCD xác định Bên B là cá nhân (12 số) thì chuẩn hóa theo tên người;
        # ngược lại chuẩn hóa theo tên doanh nghiệp (áp dụng synonyms.json Việt/Anh).
        if party_b_entity_type == EntityType.INDIVIDUAL:
            norm_value = normalize_person_name(value)
            return bool(norm_value) and norm_value in normalize_person_name(matched_text)
        norm_value = normalize_company_name(value)
        return bool(norm_value) and norm_value in normalize_company_name(matched_text)

    if field_name == "party_b_legal_representative":
        norm_value = normalize_person_name(value)
        if not norm_value:
            return False
        return norm_value in normalize_person_name(matched_text)

    if field_name == "payment_terms":
        norm_value = normalize_text(value)
        norm_matched = normalize_text(matched_text)
        if not norm_value or not norm_matched:
            return False
        # Nếu value dài hơn đoạn khớp gốc thì không thể chỉ là đoạn trích bỏ nhãn; dùng ratio toàn chuỗi.
        if len(norm_value) > len(norm_matched):
            return fuzz.ratio(norm_value, norm_matched) >= threshold
        return fuzz.partial_ratio(norm_value, norm_matched) >= threshold

    norm_value = normalize_text(value)
    return bool(norm_value) and norm_value in normalize_text(matched_text)


class CitationVerifier:
    """Bộ kiểm chứng trích dẫn hai lớp: tồn tại quote và value-in-quote trên văn bản gốc."""

    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = float(threshold) if threshold is not None else _load_default_threshold()

    def verify_field(
        self,
        field_name: str,
        extracted: ExtractedField,
        document: IndexedDocument,
        party_b_entity_type: EntityType = EntityType.UNKNOWN,
    ) -> VerifiedField:
        """Kiểm chứng một trường trích xuất dựa trên tài liệu đã chuẩn hóa và lập chỉ mục."""
        if extracted.value is None:
            return VerifiedField(
                name=field_name,
                value=None,
                quote=extracted.quote,
                status=FieldStatus.NOT_PRESENT,
                match_score=None,
                page=None,
                chunk_id=None,
            )

        norm_quote = normalize_text(extracted.quote) if extracted.quote else ""
        if not norm_quote:
            return VerifiedField(
                name=field_name,
                value=extracted.value,
                quote=extracted.quote,
                status=FieldStatus.QUOTE_NOT_FOUND,
                match_score=None,
                page=None,
                chunk_id=None,
            )

        score, span_start, span_end = _find_quote_match(norm_quote, document.full_text)
        if score < self.threshold:
            return VerifiedField(
                name=field_name,
                value=extracted.value,
                quote=extracted.quote,
                status=FieldStatus.QUOTE_NOT_FOUND,
                match_score=score,
                page=None,
                chunk_id=None,
            )

        chunk_id, page = _locate_chunk(span_start, document.spans)
        # Dùng đoạn văn gốc tại vị trí khớp (không tin chuỗi quote do LLM tự gõ lại) để kiểm tra value.
        matched_text = document.full_text[span_start:span_end]
        if not _is_value_in_matched_text(
            field_name,
            extracted.value,
            matched_text,
            self.threshold,
            party_b_entity_type=party_b_entity_type,
        ):
            return VerifiedField(
                name=field_name,
                value=extracted.value,
                quote=extracted.quote,
                status=FieldStatus.VALUE_NOT_IN_QUOTE,
                match_score=score,
                page=page,
                chunk_id=chunk_id,
            )

        return VerifiedField(
            name=field_name,
            value=extracted.value,
            quote=extracted.quote,
            status=FieldStatus.VERIFIED,
            match_score=score,
            page=page,
            chunk_id=chunk_id,
        )

    def verify(
        self,
        raw_extraction: RawExtraction,
        chunks: Sequence[dict],
    ) -> list[VerifiedField]:
        """Kiểm chứng toàn bộ 7 trường trích xuất trên danh sách chunk của tài liệu."""
        document = _build_indexed_document(chunks)
        # Suy loại chủ thể Bên B từ mã số thuế / CCCD để chọn chuẩn hóa phù hợp khi kiểm tra party_b_name.
        party_b_entity_type = classify_entity_by_tax_code(raw_extraction.party_b_tax_code.value)
        results: list[VerifiedField] = []
        for field_name in EXTRACTION_FIELD_NAMES:
            extracted = getattr(raw_extraction, field_name)
            results.append(
                self.verify_field(
                    field_name,
                    extracted,
                    document,
                    party_b_entity_type=party_b_entity_type,
                )
            )
        return results


def verify_citations(
    raw_extraction: RawExtraction,
    chunks: Sequence[dict],
    threshold: float | None = None,
) -> list[VerifiedField]:
    """Hàm tiện ích chạy CitationVerifier với ngưỡng cấu hình hoặc ngưỡng truyền vào."""
    return CitationVerifier(threshold=threshold).verify(raw_extraction, chunks)
