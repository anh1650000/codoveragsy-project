from app.extraction.schema import ExtractedField, FieldStatus, RawExtraction
from app.guardrails.citation_verifier import CitationVerifier


def _make_raw_extraction(**overrides: tuple[str | None, str | None]) -> RawExtraction:
    defaults: dict[str, tuple[str | None, str | None]] = {
        "party_a_name": ("Công ty TNHH Giải pháp Mekong", "BÊN A: Công ty TNHH Giải pháp Mekong"),
        "party_b_name": ("Công ty TNHH An Phát", "BÊN B: Công ty TNHH An Phát"),
        "party_b_tax_code": ("0310000001", "Mã số thuế: 0310000001."),
        "party_b_legal_representative": ("Nguyễn Minh Anh", "Người đại diện: Nguyễn Minh Anh."),
        "contract_value": ("500.000.000 đồng", "Giá trị hợp đồng: 500.000.000 đồng."),
        "effective_date": ("01/03/2026", "Hôm nay, ngày 01 tháng 03 năm 2026, các bên gồm:"),
        "payment_terms": (
            "Bên A thanh toán trong vòng 15 ngày kể từ ngày nghiệm thu.",
            "Bên A thanh toán trong vòng 15 ngày kể từ ngày nghiệm thu.",
        ),
    }
    defaults.update(overrides)
    payload = {
        name: ExtractedField(value=val, quote=quote)
        for name, (val, quote) in defaults.items()
    }
    return RawExtraction.model_validate(payload)


def _sample_chunks() -> list[dict]:
    return [
        {"chunk_id": 0, "page": 1, "text": "HỢP ĐỒNG CUNG CẤP DỊCH VỤ"},
        {"chunk_id": 1, "page": 1, "text": "Hôm nay, ngày 01 tháng 03 năm 2026, các bên gồm:"},
        {"chunk_id": 2, "page": 1, "text": "BÊN A: Công ty TNHH Giải pháp Mekong"},
        {"chunk_id": 3, "page": 1, "text": "BÊN B: Công ty TNHH An Phát"},
        {"chunk_id": 4, "page": 1, "text": "Mã số thuế: 0310000001."},
        {"chunk_id": 5, "page": 1, "text": "Người đại diện: Nguyễn Minh Anh."},
        {"chunk_id": 6, "page": 2, "text": "Giá trị hợp đồng: 500.000.000 đồng."},
        {"chunk_id": 7, "page": 2, "text": "Bên A thanh toán trong vòng 15 ngày kể từ ngày nghiệm thu."},
    ]


def test_verifier_accepts_valid_quotes_and_computes_page_chunk_by_code():
    verifier = CitationVerifier(threshold=85)
    raw = _make_raw_extraction(
        contract_value=("500 triệu", "Giá trị hợp đồng: 500.000.000 đồng."),
        party_b_name=("Công ty Trách nhiệm hữu hạn An Phát", "BÊN B: Công ty TNHH An Phát"),
    )

    verified = {item.name: item for item in verifier.verify(raw, _sample_chunks())}

    assert all(item.status == FieldStatus.VERIFIED for item in verified.values())
    assert verified["party_b_tax_code"].page == 1
    assert verified["party_b_tax_code"].chunk_id == 4
    assert verified["contract_value"].page == 2
    assert verified["contract_value"].chunk_id == 6
    assert verified["contract_value"].match_score == 100.0


def test_verifier_preserves_none_page_for_docx_chunks():
    docx_chunks = [
        {**chunk, "page": None} for chunk in _sample_chunks()
    ]
    verifier = CitationVerifier(threshold=85)
    verified = {item.name: item for item in verifier.verify(_make_raw_extraction(), docx_chunks)}

    assert verified["contract_value"].status == FieldStatus.VERIFIED
    assert verified["contract_value"].page is None
    assert verified["contract_value"].chunk_id == 6


def test_verifier_detects_fabricated_and_missing_quotes():
    verifier = CitationVerifier(threshold=85)
    raw = _make_raw_extraction(
        party_b_name=("Công ty TNHH XYZ", "Đoạn văn hoàn toàn bịa không hề có trong tài liệu."),
        party_b_tax_code=("0310000001", None),
    )

    verified = {item.name: item for item in verifier.verify(raw, _sample_chunks())}

    assert verified["party_b_name"].status == FieldStatus.QUOTE_NOT_FOUND
    assert verified["party_b_name"].match_score is not None
    assert verified["party_b_name"].match_score < 85
    assert verified["party_b_name"].page is None
    assert verified["party_b_name"].chunk_id is None

    assert verified["party_b_tax_code"].status == FieldStatus.QUOTE_NOT_FOUND
    assert verified["party_b_tax_code"].match_score is None


def test_verifier_detects_value_not_in_quote_across_field_types():
    verifier = CitationVerifier(threshold=85)
    raw = _make_raw_extraction(
        party_a_name=("Công ty TNHH Sai Tên", "BÊN A: Công ty TNHH Giải pháp Mekong"),
        party_b_tax_code=("0310000099", "Mã số thuế: 0310000001."),
        party_b_legal_representative=("Trần Quốc Bảo", "Người đại diện: Nguyễn Minh Anh."),
        contract_value=("5.000.000.000 đồng", "Giá trị hợp đồng: 500.000.000 đồng."),
        effective_date=("02/03/2026", "Hôm nay, ngày 01 tháng 03 năm 2026, các bên gồm:"),
        payment_terms=(
            "Thanh toán 100% trước khi giao hàng.",
            "Bên A thanh toán trong vòng 15 ngày kể từ ngày nghiệm thu.",
        ),
    )

    verified = {item.name: item for item in verifier.verify(raw, _sample_chunks())}

    for field_name in (
        "party_a_name",
        "party_b_tax_code",
        "party_b_legal_representative",
        "contract_value",
        "effective_date",
        "payment_terms",
    ):
        assert verified[field_name].status == FieldStatus.VALUE_NOT_IN_QUOTE
        assert verified[field_name].match_score == 100.0
        assert verified[field_name].chunk_id is not None


def test_verifier_checks_value_against_original_document_span_not_llm_quote():
    # LLM cố tình sửa nhẹ 1 chữ số trong quote ("900.000.000" thay cho "500.000.000") nên quote vẫn
    # đạt ngưỡng khớp chuỗi mờ (>85%). Verifier phải đối chiếu value trên đoạn gốc tại vị trí khớp
    # ("500.000.000") chứ không tin chuỗi quote LLM tự gõ, qua đó bắt được VALUE_NOT_IN_QUOTE.
    verifier = CitationVerifier(threshold=85)
    raw = _make_raw_extraction(
        contract_value=("900.000.000 đồng", "Giá trị hợp đồng: 900.000.000 đồng."),
    )

    verified = {item.name: item for item in verifier.verify(raw, _sample_chunks())}
    assert verified["contract_value"].status == FieldStatus.VALUE_NOT_IN_QUOTE
    assert verified["contract_value"].chunk_id == 6


def test_verifier_marks_null_field_as_not_present():
    verifier = CitationVerifier(threshold=85)
    raw = _make_raw_extraction(
        party_b_tax_code=(None, None),
        payment_terms=(None, None),
    )

    verified = {item.name: item for item in verifier.verify(raw, _sample_chunks())}

    assert verified["party_b_tax_code"].status == FieldStatus.NOT_PRESENT
    assert verified["party_b_tax_code"].match_score is None
    assert verified["party_b_tax_code"].chunk_id is None
    assert verified["payment_terms"].status == FieldStatus.NOT_PRESENT


def test_verifier_handles_quote_spanning_two_chunks_using_start_chunk():
    chunks = [
        {"chunk_id": 0, "page": 1, "text": "HỢP ĐỒNG DỊCH VỤ"},
        {"chunk_id": 1, "page": 1, "text": "Giá trị hợp đồng:"},
        {"chunk_id": 2, "page": 2, "text": "500.000.000 đồng theo thỏa thuận."},
    ]
    raw = _make_raw_extraction(
        party_a_name=(None, None),
        party_b_name=(None, None),
        party_b_tax_code=(None, None),
        party_b_legal_representative=(None, None),
        effective_date=(None, None),
        payment_terms=(None, None),
        contract_value=("500.000.000 đồng", "Giá trị hợp đồng: 500.000.000 đồng"),
    )

    verifier = CitationVerifier(threshold=85)
    verified = {item.name: item for item in verifier.verify(raw, chunks)}

    assert verified["contract_value"].status == FieldStatus.VERIFIED
    # Quy ước Lựa chọn 1: quote vắt qua chunk 1 (trang 1) và chunk 2 (trang 2) -> lấy chunk bắt đầu.
    assert verified["contract_value"].chunk_id == 1
    assert verified["contract_value"].page == 1


def test_verifier_tolerates_minor_noise_whitespace_linebreaks_and_missing_colon():
    verifier = CitationVerifier(threshold=85)
    raw = _make_raw_extraction(
        party_b_name=(
            "Công ty TNHH An Phát",
            "BÊN  B:\u00a0  Công ty\n   TNHH\u200b An Phát",
        ),
        party_b_tax_code=(
            "0310000001",
            "Mã số thuế 0310000001",
        ),
    )

    verified = {item.name: item for item in verifier.verify(raw, _sample_chunks())}

    assert verified["party_b_name"].status == FieldStatus.VERIFIED
    assert verified["party_b_name"].match_score == 100.0
    assert verified["party_b_tax_code"].status == FieldStatus.VERIFIED
    assert verified["party_b_tax_code"].match_score >= 85


def test_verifier_rejects_hallucinated_quote_longer_than_short_document():
    short_chunks = [{"chunk_id": 0, "page": 1, "text": "BÊN B: Công ty TNHH An Phát"}]
    raw = _make_raw_extraction(
        party_a_name=(None, None),
        party_b_tax_code=(None, None),
        party_b_legal_representative=(None, None),
        contract_value=(None, None),
        effective_date=(None, None),
        payment_terms=(None, None),
        party_b_name=(
            "Công ty TNHH An Phát",
            "BÊN B: Công ty TNHH An Phát với vốn điều lệ bịa đặt thêm một đoạn rất dài không hề tồn tại",
        ),
    )

    verifier = CitationVerifier(threshold=85)
    verified = {item.name: item for item in verifier.verify(raw, short_chunks)}
    assert verified["party_b_name"].status == FieldStatus.QUOTE_NOT_FOUND


def test_verifier_supports_english_contract_foreign_currency_and_currency_mismatch():
    english_chunks = [
        {"chunk_id": 0, "page": 1, "text": "SERVICE AGREEMENT"},
        {"chunk_id": 1, "page": 1, "text": "Effective Date: March 1, 2026"},
        {"chunk_id": 2, "page": 1, "text": "Party A: Mekong Tech Joint Stock Company"},
        {"chunk_id": 3, "page": 1, "text": "Party B: Sunrise Co., Ltd."},
        {"chunk_id": 4, "page": 1, "text": "Tax Code: 0310000002-001"},
        {"chunk_id": 5, "page": 1, "text": "Contract Value: 1,000.0$ (one thousand USD)."},
        {"chunk_id": 6, "page": 1, "text": "Payment within 15 days after acceptance."},
    ]
    raw_ok = _make_raw_extraction(
        party_a_name=("Mekong Tech JSC", "Party A: Mekong Tech Joint Stock Company"),
        party_b_name=("Sunrise Limited", "Party B: Sunrise Co., Ltd."),
        party_b_tax_code=("0310000002", "Tax Code: 0310000002-001"),
        party_b_legal_representative=(None, None),
        contract_value=("1000 usd", "Contract Value: 1,000.0$ (one thousand USD)."),
        effective_date=("2026-03-01", "Effective Date: March 1, 2026"),
        payment_terms=("Payment within 15 days after acceptance.", "Payment within 15 days after acceptance."),
    )

    verifier = CitationVerifier(threshold=85)
    verified_ok = {item.name: item for item in verifier.verify(raw_ok, english_chunks)}
    assert verified_ok["party_a_name"].status == FieldStatus.VERIFIED
    assert verified_ok["party_b_name"].status == FieldStatus.VERIFIED
    assert verified_ok["party_b_tax_code"].status == FieldStatus.VERIFIED
    assert verified_ok["contract_value"].status == FieldStatus.VERIFIED
    assert verified_ok["effective_date"].status == FieldStatus.VERIFIED

    # Sai loại tiền tệ (VND thay vì USD) phải bị bắt VALUE_NOT_IN_QUOTE dù cùng con số 1000.
    raw_wrong_cur = _make_raw_extraction(
        party_a_name=(None, None),
        party_b_name=(None, None),
        party_b_tax_code=(None, None),
        party_b_legal_representative=(None, None),
        effective_date=(None, None),
        payment_terms=(None, None),
        contract_value=("1000 VND", "Contract Value: 1,000.0$ (one thousand USD)."),
    )
    verified_wrong_cur = {item.name: item for item in verifier.verify(raw_wrong_cur, english_chunks)}
    assert verified_wrong_cur["contract_value"].status == FieldStatus.VALUE_NOT_IN_QUOTE


def test_verifier_handles_individual_party_b_with_12_digit_cccd():
    chunks = [
        {"chunk_id": 0, "page": 1, "text": "BÊN B: Ông Trần Văn Minh"},
        {"chunk_id": 1, "page": 1, "text": "CCCD/MST cá nhân: 079200012345."},
    ]
    verifier = CitationVerifier(threshold=85)

    raw_ok = _make_raw_extraction(
        party_a_name=(None, None),
        party_b_legal_representative=(None, None),
        contract_value=(None, None),
        effective_date=(None, None),
        payment_terms=(None, None),
        party_b_name=("Trần Văn Minh", "BÊN B: Ông Trần Văn Minh"),
        party_b_tax_code=("079200012345", "CCCD/MST cá nhân: 079200012345."),
    )
    verified_ok = {item.name: item for item in verifier.verify(raw_ok, chunks)}
    assert verified_ok["party_b_name"].status == FieldStatus.VERIFIED
    assert verified_ok["party_b_tax_code"].status == FieldStatus.VERIFIED

    # Sai 2 số cuối hoặc bị cắt cụt còn 10 số đều phải bị bắt VALUE_NOT_IN_QUOTE.
    for bad_cccd in ("079200012399", "0792000123"):
        raw_bad = _make_raw_extraction(
            party_a_name=(None, None),
            party_b_legal_representative=(None, None),
            contract_value=(None, None),
            effective_date=(None, None),
            payment_terms=(None, None),
            party_b_name=("Trần Văn Minh", "BÊN B: Ông Trần Văn Minh"),
            party_b_tax_code=(bad_cccd, "CCCD/MST cá nhân: 079200012345."),
        )
        verified_bad = {item.name: item for item in verifier.verify(raw_bad, chunks)}
        assert verified_bad["party_b_tax_code"].status == FieldStatus.VALUE_NOT_IN_QUOTE


def test_known_limitation_multi_number_quote_accepts_wrong_field_number_as_verified():
    # Known limitation đã ghi nhận trong thiết kế Tuần 3:
    # Khi một câu quote chứa nhiều con số cùng loại (ở đây vừa có giá trị hợp đồng 500 triệu vừa có
    # mức tạm ứng 100 triệu), hàm kiểm tra value-in-quote chỉ kiểm tra xem số trong value có thuộc tập
    # ứng viên trong quote hay không. Vì chưa phân tích quan hệ ngữ nghĩa giữa nhãn ("tạm ứng" vs
    # "giá trị hợp đồng") và con số, nếu LLM bốc nhầm 100 triệu vào contract_value thì vẫn ra VERIFIED.
    chunks = [
        {
            "chunk_id": 0,
            "page": 1,
            "text": "Giá trị hợp đồng: 500.000.000 đồng, bên A tạm ứng trước 100.000.000 đồng.",
        }
    ]
    raw = _make_raw_extraction(
        party_a_name=(None, None),
        party_b_name=(None, None),
        party_b_tax_code=(None, None),
        party_b_legal_representative=(None, None),
        effective_date=(None, None),
        payment_terms=(None, None),
        contract_value=(
            "100.000.000 đồng",
            "Giá trị hợp đồng: 500.000.000 đồng, bên A tạm ứng trước 100.000.000 đồng.",
        ),
    )

    verifier = CitationVerifier(threshold=85)
    verified = {item.name: item for item in verifier.verify(raw, chunks)}
    assert verified["contract_value"].status == FieldStatus.VERIFIED
