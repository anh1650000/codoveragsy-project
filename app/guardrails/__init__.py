"""Các module kiểm chứng trích dẫn và chuẩn hóa dữ liệu bằng code thuần."""

from app.guardrails.citation_verifier import CitationVerifier, verify_citations
from app.guardrails.normalizers import (
    COMPANY_NAME_REPLACEMENTS,
    EntityType,
    MoneyAmount,
    classify_entity_by_tax_code,
    extract_money_candidates,
    extract_vn_date_candidates,
    extract_vnd_candidates,
    normalize_company_name,
    normalize_person_name,
    normalize_tax_code,
    normalize_text,
    parse_money,
    parse_vn_date,
    parse_vnd,
)

__all__ = [
    "COMPANY_NAME_REPLACEMENTS",
    "CitationVerifier",
    "EntityType",
    "MoneyAmount",
    "classify_entity_by_tax_code",
    "extract_money_candidates",
    "extract_vn_date_candidates",
    "extract_vnd_candidates",
    "normalize_company_name",
    "normalize_person_name",
    "normalize_tax_code",
    "normalize_text",
    "parse_money",
    "parse_vn_date",
    "parse_vnd",
    "verify_citations",
]
