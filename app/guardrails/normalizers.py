"""Các hàm chuẩn hóa dữ liệu Việt Nam và quốc tế cho kiểm chứng trích dẫn bằng code thuần."""

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path

_SYNONYMS_PATH = Path(__file__).with_name("synonyms.json")


def _load_synonyms(path: Path = _SYNONYMS_PATH) -> dict:
    """Nạp toàn bộ bảng từ đồng nghĩa, tháng tiếng Anh, đơn vị và tiền tệ từ synonyms.json."""
    return json.loads(path.read_text(encoding="utf-8"))


_SYNONYMS_DATA = _load_synonyms()

# Nạp các bảng ánh xạ từ synonyms.json để dễ mở rộng ngoài code và ép đúng kiểu dữ liệu khi sử dụng.
COMPANY_NAME_REPLACEMENTS: tuple[tuple[str, str], ...] = tuple(
    (
        unicodedata.normalize("NFC", str(source)).lower(),
        unicodedata.normalize("NFC", str(target)).lower(),
    )
    for source, target in _SYNONYMS_DATA.get("company_name_replacements", {}).items()
)
_ENGLISH_MONTHS: dict[str, int] = {
    unicodedata.normalize("NFC", str(name)).lower(): int(month)
    for name, month in _SYNONYMS_DATA.get("english_months", {}).items()
}
_UNIT_MULTIPLIERS: dict[str, Decimal] = {
    unicodedata.normalize("NFC", str(unit)).lower(): Decimal(str(multiplier))
    for unit, multiplier in _SYNONYMS_DATA.get("unit_multipliers", {}).items()
}
_CURRENCY_ALIASES: dict[str, str] = {
    unicodedata.normalize("NFC", str(alias)).lower(): unicodedata.normalize("NFC", str(code)).upper()
    for alias, code in _SYNONYMS_DATA.get("currency_aliases", {}).items()
}


class EntityType(str, Enum):
    """Phân loại chủ thể Bên B suy ra từ mã số thuế / căn cước công dân."""

    COMPANY = "COMPANY"
    INDIVIDUAL = "INDIVIDUAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class MoneyAmount:
    """Giá trị tiền tệ đã chuẩn hóa kèm mã tiền tệ (VND, USD, EUR...)."""

    amount: Decimal
    currency: str = "VND"


_ZERO_WIDTH_AND_SOFT_HYPHEN_RE = re.compile(r"[\u200b-\u200d\ufeff\u00ad]")
_WHITESPACE_RE = re.compile(r"\s+")
_PUNCTUATION_RE = re.compile(r"[^\w\s]")


def _build_english_month_pattern(months: dict[str, int]) -> str:
    """Sinh regex tên tháng tiếng Anh từ _ENGLISH_MONTHS, ưu tiên chuỗi dài trước."""
    keys = sorted((key for key in months if key), key=len, reverse=True)
    return "|".join(re.escape(key) for key in keys)


def _build_currency_patterns(aliases: dict[str, str]) -> tuple[str, str]:
    """Sinh regex tiền tệ đặt trước và đặt sau số từ _CURRENCY_ALIASES."""
    prefix_parts: list[str] = []
    suffix_parts: list[str] = []
    for alias in sorted((key for key in aliases if key), key=len, reverse=True):
        escaped = re.escape(alias)
        if alias[-1].isalpha():
            token_re = rf"{escaped}(?![a-zà-ỹ0-9])"
            # Tránh nhận nhầm "đ" / "đồng" đứng đầu cụm chữ (vd "điều 1") thành tiền tệ đặt trước số.
            if alias not in {"đ", "đồng"}:
                prefix_parts.append(token_re)
            suffix_parts.append(token_re)
        else:
            prefix_parts.append(escaped)
            # Ký hiệu tiền tệ đi sau số không được ăn nhầm ký hiệu mở đầu của số kế tiếp (vd "$1,000 $500").
            suffix_parts.append(rf"{escaped}(?!\d)")
    return "|".join(prefix_parts), "|".join(suffix_parts)


def _build_money_regex(
    unit_multipliers: dict[str, Decimal],
    currency_aliases: dict[str, str],
) -> re.Pattern[str]:
    """Dựng regex nhận diện tiền tệ và đơn vị nhân động theo cấu hình trong synonyms.json."""
    prefix_cur, suffix_cur = _build_currency_patterns(currency_aliases)
    non_empty_units = sorted((u for u in unit_multipliers if u), key=len, reverse=True)
    all_units = "|".join(re.escape(u) for u in non_empty_units)
    billion_units = "|".join(
        re.escape(u) for u in non_empty_units if unit_multipliers[u] == Decimal("1000000000")
    )
    million_units = "|".join(
        re.escape(u) for u in non_empty_units if unit_multipliers[u] == Decimal("1000000")
    )

    body_branches: list[str] = []
    if billion_units and million_units:
        body_branches.append(
            rf"(?P<b_val>\d+(?:[.,]\d+)*)\s*(?P<b_unit>{billion_units})(?![a-zà-ỹ0-9])\s+"
            rf"(?P<m_val>\d+(?:[.,]\d+)*)\s*(?P<m_unit>{million_units})(?![a-zà-ỹ0-9])"
        )
    unit_suffix = rf"(?:\s*(?P<unit>{all_units})(?![a-zà-ỹ0-9]))?" if all_units else ""
    body_branches.append(rf"(?P<val>\d+(?:[.,]\d+)*){unit_suffix}")

    prefix_part = rf"(?:(?P<pre_cur>{prefix_cur})\s*)?" if prefix_cur else ""
    suffix_part = rf"(?:\s*(?P<suf_cur>{suffix_cur}))?" if suffix_cur else ""
    return re.compile(
        rf"(?<![a-zà-ỹ0-9.,])"
        rf"{prefix_part}"
        rf"(?:{'|'.join(body_branches)})"
        rf"{suffix_part}"
    )


_EN_MONTH_PATTERN = _build_english_month_pattern(_ENGLISH_MONTHS)

# Regex nhận diện ngày tiếng Việt và ngày quốc tế (ISO, DD/MM/YYYY, MM/DD/YYYY không nhập nhằng, Month D YYYY).
_WRITTEN_VN_DATE_RE = re.compile(r"(?:ngày\s+)?(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})")
_EN_MONTH_DAY_YEAR_RE = re.compile(
    rf"\b(?P<month>{_EN_MONTH_PATTERN})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s+|\s+)(?P<year>\d{{4}})\b"
)
_EN_DAY_MONTH_YEAR_RE = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:\s+of)?\s+(?P<month>{_EN_MONTH_PATTERN})\.?(?:\s*,?\s+|\s+)(?P<year>\d{{4}})\b"
)
_ISO_DATE_RE = re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")

_MONEY_AMOUNT_RE = _build_money_regex(_UNIT_MULTIPLIERS, _CURRENCY_ALIASES)


def normalize_text(text: str) -> str:
    """Chuẩn hóa văn bản về dạng so khớp ổn định (NFC, chữ thường, một dấu cách)."""
    # PDF và DOCX có thể lưu cùng chữ tiếng Việt ở dạng NFC hoặc NFD; ép về NFC để so khớp nhất quán.
    normalized = unicodedata.normalize("NFC", text).lower()
    # Thay khoảng trắng không ngắt (\u00a0) từ Word/HTML bằng dấu cách ASCII chuẩn.
    normalized = normalized.replace("\u00a0", " ")
    # Loại ký tự zero-width và soft hyphen vốn vô hình khi đọc nhưng làm lệch vị trí so chuỗi.
    normalized = _ZERO_WIDTH_AND_SOFT_HYPHEN_RE.sub("", normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def _parse_numeric_token(raw_number: str, has_multiplier: bool) -> Decimal | None:
    """Chuyển chuỗi số có dấu '.' hoặc ',' thành Decimal, phân biệt dấu nghìn và dấu thập phân."""
    if "." in raw_number and "," in raw_number:
        # Hỗ trợ cả định dạng Mỹ/Anh ("1,000.50") lẫn Việt/châu Âu ("1.000,50"):
        # dấu xuất hiện sau cùng với <= 2 chữ số sau nó là dấu thập phân.
        last_sep_idx = max(raw_number.rfind("."), raw_number.rfind(","))
        decimal_part = raw_number[last_sep_idx + 1 :]
        integer_part = re.sub(r"[.,]", "", raw_number[:last_sep_idx])
        if not integer_part or len(decimal_part) > 2:
            return None
        normalized_num = f"{integer_part}.{decimal_part}"
    elif "." in raw_number or "," in raw_number:
        sep = "." if "." in raw_number else ","
        parts = raw_number.split(sep)
        if len(parts) > 2:
            # Nhiều dấu phân cách cùng loại chỉ hợp lệ khi các nhóm sau đều đúng 3 chữ số (vd 1,000,000).
            if any(len(part) != 3 for part in parts[1:]):
                return None
            normalized_num = "".join(parts)
        else:
            left, right = parts
            # Nhóm đúng 3 chữ số sau dấu là phân cách hàng nghìn ("500.000", "1,000", "1.500 triệu"),
            # trừ khi đi kèm đơn vị nhân có phần nguyên là 0 (vd "0.500 tỷ") hoặc 1-2 chữ số thập phân ("1000.0", "100.50").
            if len(right) == 3 and (not has_multiplier or left != "0"):
                normalized_num = f"{left}{right}"
            else:
                normalized_num = f"{left}.{right}"
    else:
        normalized_num = raw_number

    try:
        return Decimal(normalized_num)
    except InvalidOperation:
        return None


def _finalize_decimal(amount: Decimal) -> Decimal:
    """Rút gọn phần thập phân .0 dư thừa (vd 1000.0 -> 1000) để so khớp nhất quán."""
    if amount == amount.to_integral_value():
        return amount.quantize(Decimal("1"))
    return amount.normalize()


def _resolve_currency(pre_cur: str | None, suf_cur: str | None) -> str:
    """Quy đổi ký hiệu/mã tiền tệ sang mã ISO thống nhất (mặc định VND nếu hợp đồng không ghi)."""
    raw = suf_cur or pre_cur
    if not raw:
        return "VND"
    return _CURRENCY_ALIASES.get(raw.lower(), raw.upper())


def _mask_date_substrings(normalized_text: str) -> str:
    """Che tạm các cụm ngày Việt và quốc tế trước khi trích số tiền để tránh nhiễu số năm/ngày."""
    cleaned = normalized_text
    patterns: list[re.Pattern[str]] = [_WRITTEN_VN_DATE_RE]
    if _EN_MONTH_PATTERN:
        patterns.extend((_EN_MONTH_DAY_YEAR_RE, _EN_DAY_MONTH_YEAR_RE))
    patterns.extend((_ISO_DATE_RE, _NUMERIC_DATE_RE))
    for pattern in patterns:
        cleaned = pattern.sub(" ", cleaned)
    return cleaned


def extract_money_candidates(text: str) -> list[MoneyAmount]:
    """Trích mọi số tiền ứng viên kèm đơn vị tiền tệ (VND, USD, EUR...) trong một đoạn văn bản."""
    normalized = normalize_text(text)
    cleaned = _mask_date_substrings(normalized)

    candidates: list[MoneyAmount] = []
    for match in _MONEY_AMOUNT_RE.finditer(cleaned):
        groups = match.groupdict()
        currency = _resolve_currency(groups.get("pre_cur"), groups.get("suf_cur"))
        b_val = groups.get("b_val")
        m_val = groups.get("m_val")
        if b_val is not None and m_val is not None:
            b_unit = groups.get("b_unit")
            m_unit = groups.get("m_unit")
            billions = _parse_numeric_token(b_val, has_multiplier=True)
            millions = _parse_numeric_token(m_val, has_multiplier=True)
            if billions is None or millions is None or b_unit is None or m_unit is None:
                continue
            total = billions * _UNIT_MULTIPLIERS[b_unit] + millions * _UNIT_MULTIPLIERS[m_unit]
            candidates.append(MoneyAmount(amount=_finalize_decimal(total), currency=currency))
            continue

        raw_val = groups.get("val")
        unit = groups.get("unit")
        if raw_val is None:
            continue
        parsed = _parse_numeric_token(raw_val, has_multiplier=unit is not None)
        if parsed is None:
            continue
        multiplier = _UNIT_MULTIPLIERS[unit] if unit else Decimal("1")
        candidates.append(MoneyAmount(amount=_finalize_decimal(parsed * multiplier), currency=currency))

    return candidates


def parse_money(text: str) -> MoneyAmount | None:
    """Phân tích một giá trị tiền tệ (VND hoặc ngoại tệ) thành MoneyAmount(amount, currency)."""
    candidates = extract_money_candidates(text)
    if not candidates:
        return None
    return candidates[0]


def extract_vnd_candidates(text: str) -> list[Decimal]:
    """Trích mọi số tiền VND ứng viên trong đoạn văn (giữ tương thích với đặc tả cũ)."""
    return [item.amount for item in extract_money_candidates(text) if item.currency == "VND"]


def parse_vnd(text: str) -> Decimal | None:
    """Phân tích chuỗi giá trị tiền tệ VND sang Decimal; trả None nếu là ngoại tệ hoặc không hợp lệ."""
    candidates = extract_vnd_candidates(text)
    if not candidates:
        return None
    return candidates[0]


def _build_valid_date(year: int, month: int, day: int) -> date | None:
    if not (1900 <= year <= 2100):
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_vn_date_candidates(text: str) -> list[date]:
    """Trích mọi ngày hợp lệ (tiếng Việt, ISO, DD/MM/YYYY, ngày quốc tế bằng tiếng Anh và MM/DD/YYYY)."""
    normalized = normalize_text(text)
    found_with_pos: list[tuple[int, date]] = []
    occupied_spans: list[tuple[int, int]] = []

    def _overlaps(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in occupied_spans)

    # 1. Ngày viết bằng tiếng Việt ("ngày 01 tháng 03 năm 2026" hoặc "8 tháng 10 năm 2026").
    for match in _WRITTEN_VN_DATE_RE.finditer(normalized):
        if _overlaps(match.start(), match.end()):
            continue
        day, month, year = map(int, match.groups())
        parsed = _build_valid_date(year, month, day)
        if parsed is not None:
            occupied_spans.append((match.start(), match.end()))
            found_with_pos.append((match.start(), parsed))

    # 2. Ngày tiếng Anh ("March 1, 2026" hoặc "01 March 2026").
    if _EN_MONTH_PATTERN:
        for pattern in (_EN_MONTH_DAY_YEAR_RE, _EN_DAY_MONTH_YEAR_RE):
            for match in pattern.finditer(normalized):
                if _overlaps(match.start(), match.end()):
                    continue
                month = _ENGLISH_MONTHS.get(match.group("month"))
                if month is None:
                    continue
                day = int(match.group("day"))
                year = int(match.group("year"))
                parsed = _build_valid_date(year, month, day)
                if parsed is not None:
                    occupied_spans.append((match.start(), match.end()))
                    found_with_pos.append((match.start(), parsed))

    # 3. Định dạng ISO / năm đứng trước (YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD).
    for match in _ISO_DATE_RE.finditer(normalized):
        if _overlaps(match.start(), match.end()):
            continue
        year, month, day = map(int, match.groups())
        parsed = _build_valid_date(year, month, day)
        if parsed is not None:
            occupied_spans.append((match.start(), match.end()))
            found_with_pos.append((match.start(), parsed))

    # 4. Định dạng số DD/MM/YYYY (ưu tiên chuẩn Việt Nam khi cả 2 số <= 12) và fallback MM/DD/YYYY khi số sau > 12.
    for match in _NUMERIC_DATE_RE.finditer(normalized):
        if _overlaps(match.start(), match.end()):
            continue
        first, second, year = map(int, match.groups())
        parsed = _build_valid_date(year, second, first)
        if parsed is None and 1 <= first <= 12 and second > 12:
            parsed = _build_valid_date(year, first, second)
        if parsed is not None:
            occupied_spans.append((match.start(), match.end()))
            found_with_pos.append((match.start(), parsed))

    found_with_pos.sort(key=lambda item: item[0])
    return [item[1] for item in found_with_pos]


def parse_vn_date(text: str) -> date | None:
    """Phân tích chuỗi ngày Việt Nam hoặc ngày quốc tế sang đối tượng datetime.date."""
    candidates = extract_vn_date_candidates(text)
    if not candidates:
        return None
    return candidates[0]


def classify_entity_by_tax_code(text: str | None) -> EntityType:
    """Phân loại Bên B là doanh nghiệp (MST 10/13 số) hay cá nhân (CCCD 12 số)."""
    if not text:
        return EntityType.UNKNOWN
    digits = re.sub(r"\D", "", text)
    if len(digits) in {10, 13}:
        return EntityType.COMPANY
    if len(digits) == 12:
        return EntityType.INDIVIDUAL
    return EntityType.UNKNOWN


def normalize_tax_code(text: str) -> str:
    """Chuẩn hóa MST doanh nghiệp (cắt 10 số chính nếu là 10/13 số) hoặc giữ nguyên 12 số CCCD cá nhân."""
    digits = re.sub(r"\D", "", text)
    # Mã số thuế cá nhân dùng số định danh CCCD 12 số, không được cắt bớt về 10 số như MST doanh nghiệp.
    if len(digits) == 12:
        return digits
    if len(digits) in {10, 13}:
        return digits[:10]
    return digits


def normalize_company_name(text: str) -> str:
    """Chuẩn hóa tên công ty Việt/Anh theo bảng quy đổi trong synonyms.json và bỏ dấu câu thừa."""
    normalized = normalize_text(text)
    normalized = _PUNCTUATION_RE.sub(" ", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    for full_phrase, short_form in COMPANY_NAME_REPLACEMENTS:
        pattern = re.compile(rf"(?<!\w){re.escape(full_phrase)}(?!\w)")
        normalized = pattern.sub(short_form, normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def normalize_person_name(text: str) -> str:
    """Chuẩn hóa họ tên cá nhân / người đại diện bằng cách bỏ dấu câu thừa và gộp khoảng trắng."""
    normalized = normalize_text(text)
    normalized = _PUNCTUATION_RE.sub(" ", normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()
