from datetime import date
from decimal import Decimal
import unicodedata

from app.guardrails.normalizers import (
    _CURRENCY_ALIASES,
    _ENGLISH_MONTHS,
    _SYNONYMS_PATH,
    _UNIT_MULTIPLIERS,
    COMPANY_NAME_REPLACEMENTS,
    EntityType,
    MoneyAmount,
    _load_synonyms,
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


def test_normalize_text_handles_unicode_whitespace_and_invisible_chars():
    nfd_text = unicodedata.normalize("NFD", "Cộng hòa\u00a0Xã\u200b hội\u00ad\n  Chủ   nghĩa")
    assert normalize_text(nfd_text) == "cộng hòa xã hội chủ nghĩa"


def test_parse_vnd_supports_diverse_vietnamese_formats():
    assert parse_vnd("2.000.000.000 đồng") == Decimal("2000000000")
    assert parse_vnd("2 tỷ đồng") == Decimal("2000000000")
    assert parse_vnd("500 triệu") == Decimal("500000000")
    assert parse_vnd("VND 500.000.000") == Decimal("500000000")
    assert parse_vnd("500.000.000 VNĐ.") == Decimal("500000000")
    assert parse_vnd("1,5 tỷ") == Decimal("1500000000")
    assert parse_vnd("1.5 tỷ đồng") == Decimal("1500000000")
    assert parse_vnd("1.500 triệu") == Decimal("1500000000")
    assert parse_vnd("2 tỷ 500 triệu") == Decimal("2500000000")
    assert parse_vnd("500,000,000 VND") == Decimal("500000000")
    assert parse_vnd("500.000.000,50 đồng") == Decimal("500000000.5")
    assert parse_vnd("500.000.000 đồng (bằng chữ: theo thỏa thuận của hai bên).") == Decimal(
        "500000000"
    )


def test_parse_money_handles_foreign_currencies_and_international_decimals():
    assert parse_money("1,000.0$") == MoneyAmount(Decimal("1000"), "USD")
    assert parse_money("1000 usd") == MoneyAmount(Decimal("1000"), "USD")
    assert parse_money("$1,000.50") == MoneyAmount(Decimal("1000.5"), "USD")
    assert parse_money("1.000,50 EUR") == MoneyAmount(Decimal("1000.5"), "EUR")
    assert parse_money("€2,500.00") == MoneyAmount(Decimal("2500"), "EUR")
    assert parse_money("£500") == MoneyAmount(Decimal("500"), "GBP")
    assert parse_money("¥100,000") == MoneyAmount(Decimal("100000"), "JPY")
    assert parse_money("2.5 million USD") == MoneyAmount(Decimal("2500000"), "USD")
    assert parse_money("1.2 billion EUR") == MoneyAmount(Decimal("1200000000"), "EUR")
    assert parse_money("500k USD") == MoneyAmount(Decimal("500000"), "USD")
    assert parse_money("1,500 million USD") == MoneyAmount(Decimal("1500000000"), "USD")
    assert parse_vnd("1000 usd") is None


def test_extract_money_candidates_handles_packed_foreign_currency_and_avoids_units_like_meter():
    assert extract_money_candidates("1,000.0$(1000 usd)") == [
        MoneyAmount(Decimal("1000"), "USD"),
        MoneyAmount(Decimal("1000"), "USD"),
    ]
    assert extract_money_candidates("$1,000 $500") == [
        MoneyAmount(Decimal("1000"), "USD"),
        MoneyAmount(Decimal("500"), "USD"),
    ]
    # Chữ 'm' đứng sau số trong hợp đồng thường là mét, không được hiểu nhầm thành million.
    assert parse_money("100m") == MoneyAmount(Decimal("100"), "VND")


def test_parse_vnd_returns_none_for_non_money_or_date_text():
    assert parse_vnd("Không có thông tin") is None
    assert parse_vnd("Ngày 01/03/2026") is None
    assert parse_vnd("ngày 2 tháng 4 năm 2026") is None
    assert parse_money("Effective on March 1, 2026") is None
    assert parse_money("Date: 03/25/2026") is None


def test_extract_vnd_candidates_finds_all_amounts_without_date_noise():
    text = (
        "Ngày 01/03/2026, giá trị hợp đồng là 500.000.000 đồng, "
        "tạm ứng 150 triệu đồng và giữ lại 50 triệu."
    )
    assert extract_vnd_candidates(text) == [
        Decimal("500000000"),
        Decimal("150000000"),
        Decimal("50000000"),
    ]


def test_parse_vn_date_supports_vietnamese_and_international_formats():
    assert parse_vn_date("ngày 01 tháng 03 năm 2026") == date(2026, 3, 1)
    assert parse_vn_date("Hôm nay, ngày 2 tháng 4 năm 2026, các bên gồm:") == date(2026, 4, 2)
    assert parse_vn_date("8 tháng 10 năm 2026") == date(2026, 10, 8)
    assert parse_vn_date("01/03/2026") == date(2026, 3, 1)
    assert parse_vn_date("04-06-2026") == date(2026, 6, 4)
    assert parse_vn_date("01.03.2026") == date(2026, 3, 1)
    assert parse_vn_date("2026-03-01") == date(2026, 3, 1)
    assert parse_vn_date("2026/03/01") == date(2026, 3, 1)
    # Ngày quốc tế tiếng Anh và định dạng Mỹ khi ngày > 12.
    assert parse_vn_date("March 1, 2026") == date(2026, 3, 1)
    assert parse_vn_date("Sept. 25, 2026") == date(2026, 9, 25)
    assert parse_vn_date("1st March, 2026") == date(2026, 3, 1)
    assert parse_vn_date("25th of Dec 2026") == date(2026, 12, 25)
    assert parse_vn_date("03/25/2026") == date(2026, 3, 25)
    # Ca nhập nhằng cả hai số <= 12 vẫn ưu tiên DD/MM/YYYY theo quy ước hợp đồng Việt Nam.
    assert parse_vn_date("03/04/2026") == date(2026, 4, 3)
    assert parse_vn_date("31/02/2026") is None
    assert parse_vn_date("không có ngày") is None

    multi = "Signed on March 1, 2026, effective from 15/03/2026."
    assert extract_vn_date_candidates(multi) == [date(2026, 3, 1), date(2026, 3, 15)]


def test_normalize_tax_code_and_classify_company_vs_individual():
    assert normalize_tax_code("MST: 0312345678-001") == "0312345678"
    assert normalize_tax_code("0312345678.") == "0312345678"
    assert normalize_tax_code("0312 345 678") == "0312345678"
    assert normalize_tax_code("CCCD: 079200012345") == "079200012345"
    assert normalize_tax_code("0792 0001 2345") == "079200012345"
    assert normalize_tax_code("Không có MST") == ""

    assert classify_entity_by_tax_code("0312345678") == EntityType.COMPANY
    assert classify_entity_by_tax_code("0312345678-001") == EntityType.COMPANY
    assert classify_entity_by_tax_code("079200012345") == EntityType.INDIVIDUAL
    assert classify_entity_by_tax_code("12345") == EntityType.UNKNOWN
    assert classify_entity_by_tax_code(None) == EntityType.UNKNOWN


def test_normalize_company_name_loads_synonyms_for_vietnamese_and_english():
    assert len(COMPANY_NAME_REPLACEMENTS) > 5
    assert normalize_company_name("Công ty Trách nhiệm hữu hạn An Phát") == "ct tnhh an phát"
    assert normalize_company_name("Cty TNHH An Phát.") == "ct tnhh an phát"
    assert normalize_company_name("Công ty Cổ phần Đại Việt") == "ct cp đại việt"
    assert normalize_company_name("Cty CP Đại Việt,") == "ct cp đại việt"
    assert normalize_company_name("Công ty TNHH Một thành viên Sao Biển") == "ct tnhh mtv sao biển"
    assert normalize_company_name("Công ty TNHH Thương mại và Dịch vụ An Phát") == "ct tnhh tmdv an phát"
    assert normalize_company_name("Cty TNHH TM-DV An Phát") == "ct tnhh tmdv an phát"

    assert normalize_company_name("ABC Co., Ltd.") == "abc ltd"
    assert normalize_company_name("ABC Company Limited") == "abc ltd"
    assert normalize_company_name("ABC Company Ltd.") == "abc ltd"
    assert normalize_company_name("ABC Limited") == "abc ltd"
    assert normalize_company_name("Global Limited Liability Company") == "global llc"
    assert normalize_company_name("Sunrise Joint Stock Company") == "sunrise jsc"
    assert normalize_company_name("Acme Corporation") == "acme corp"
    assert normalize_company_name("Beta Incorporated") == "beta inc"
    assert normalize_person_name("Nguyễn Minh Anh.") == "nguyễn minh anh"


def test_synonyms_json_loads_months_multipliers_and_currencies_with_expected_types():
    data = _load_synonyms(_SYNONYMS_PATH)
    assert set(data.keys()) >= {
        "company_name_replacements",
        "english_months",
        "unit_multipliers",
        "currency_aliases",
    }
    assert all(isinstance(k, str) and isinstance(v, int) for k, v in _ENGLISH_MONTHS.items())
    assert _ENGLISH_MONTHS["sept"] == 9
    assert all(isinstance(k, str) and isinstance(v, Decimal) for k, v in _UNIT_MULTIPLIERS.items())
    assert _UNIT_MULTIPLIERS["tỷ"] == Decimal("1000000000")
    assert all(isinstance(k, str) and isinstance(v, str) and v.isupper() for k, v in _CURRENCY_ALIASES.items())
    assert _CURRENCY_ALIASES["$"] == "USD"
    assert parse_money("2 billion 500 million USD") == MoneyAmount(Decimal("2500000000"), "USD")
