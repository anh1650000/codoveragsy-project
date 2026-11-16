"""Unit test cho ReconciliationEngine kiểm tra toàn diện các kịch bản đối soát độc lập."""

from decimal import Decimal
from types import SimpleNamespace

from app.extraction.schema import AuditItem, FieldStatus, VerifiedField
from app.reconciliation.engine import ReconciliationEngine


def _make_sample_master_entities():
    return [
        SimpleNamespace(
            vat_code="0310000001",
            company_name="Công ty TNHH An Phát",
            legal_representative="Nguyễn Minh Anh",
            max_contract_value=Decimal("1500000000"),
        ),
        SimpleNamespace(
            vat_code="0310000002",
            company_name="Công ty Cổ phần Bình Minh",
            legal_representative="Trần Quốc Bảo",
            max_contract_value=Decimal("2000000000"),
        ),
        SimpleNamespace(
            vat_code="0310000003",
            company_name="Công ty TNHH Cửu Long",
            legal_representative="Lê Thu Hà",
            max_contract_value=Decimal("800000000"),
        ),
    ]


def _make_verified_field(name: str, value: str | None, status: FieldStatus = FieldStatus.VERIFIED) -> VerifiedField:
    return VerifiedField(
        name=name,
        value=value,
        quote="đoạn trích kiểm chứng",
        status=status,
        match_score=100.0,
        page=1,
        chunk_id=1,
    )


def test_reconciliation_clean():
    """Khớp hoàn toàn: MST, tên, đại diện và hạn mức đều hợp lệ -> không sinh lỗi."""
    engine = ReconciliationEngine(name_match_threshold=90.0, name_score_margin=5.0)
    entities = _make_sample_master_entities()
    fields = [
        _make_verified_field("party_b_tax_code", "0310000001"),
        _make_verified_field("party_b_name", "Công ty TNHH An Phát"),
        _make_verified_field("party_b_legal_representative", "Nguyễn Minh Anh"),
        _make_verified_field("contract_value", "1.000.000.000 VND"),
    ]

    items = engine.reconcile(fields, entities)
    assert len(items) == 0


def test_reconciliation_wrong_tax_code_matching_name():
    """Sai MST: MST lạ nhưng tên công ty khớp An Phát -> IDENTITY_MISMATCH ở party_b_tax_code."""
    engine = ReconciliationEngine(name_match_threshold=90.0, name_score_margin=5.0)
    entities = _make_sample_master_entities()
    fields = [
        _make_verified_field("party_b_tax_code", "0399999999"),  # MST không có trong DB
        _make_verified_field("party_b_name", "Công ty TNHH An Phát"),
    ]

    items = engine.reconcile(fields, entities)
    assert len(items) == 1
    assert items[0].error_type == "IDENTITY_MISMATCH"
    assert items[0].field_name == "party_b_tax_code"
    assert items[0].expected_value == "0310000001"


def test_reconciliation_wrong_representative():
    """Sai đại diện: MST và tên đúng, nhưng người đại diện không khớp DB -> IDENTITY_MISMATCH."""
    engine = ReconciliationEngine(name_match_threshold=90.0, name_score_margin=5.0)
    entities = _make_sample_master_entities()
    fields = [
        _make_verified_field("party_b_tax_code", "0310000001"),
        _make_verified_field("party_b_name", "Công ty TNHH An Phát"),
        _make_verified_field("party_b_legal_representative", "Trần Văn Sai"),
    ]

    items = engine.reconcile(fields, entities)
    assert len(items) == 1
    assert items[0].error_type == "IDENTITY_MISMATCH"
    assert items[0].field_name == "party_b_legal_representative"
    assert items[0].expected_value == "Nguyễn Minh Anh"


def test_reconciliation_over_limit():
    """Vượt hạn mức: giá trị hợp đồng 2 tỷ > hạn mức 1.5 tỷ của An Phát -> VALUE_OVER_LIMIT."""
    engine = ReconciliationEngine(name_match_threshold=90.0, name_score_margin=5.0)
    entities = _make_sample_master_entities()
    fields = [
        _make_verified_field("party_b_tax_code", "0310000001"),
        _make_verified_field("party_b_name", "Công ty TNHH An Phát"),
        _make_verified_field("contract_value", "2.000.000.000 VND"),
    ]

    items = engine.reconcile(fields, entities)
    assert len(items) == 1
    assert items[0].error_type == "VALUE_OVER_LIMIT"
    assert items[0].field_name == "contract_value"
    assert items[0].expected_value == "1500000000"


def test_reconciliation_unknown_entity():
    """Công ty không tồn tại: cả MST lẫn tên đều không có trong DB -> ENTITY_NOT_FOUND."""
    engine = ReconciliationEngine(name_match_threshold=90.0, name_score_margin=5.0)
    entities = _make_sample_master_entities()
    fields = [
        _make_verified_field("party_b_tax_code", "9999999999"),
        _make_verified_field("party_b_name", "Công ty Cổ phần Hoàn Toàn Lạ"),
    ]

    items = engine.reconcile(fields, entities)
    assert len(items) == 1
    assert items[0].error_type == "ENTITY_NOT_FOUND"
    assert items[0].field_name == "party_b_tax_code"


def test_reconciliation_missing_tax_code_known_name():
    """Thiếu MST (NOT_PRESENT) nhưng tên khớp Bình Minh -> tìm thấy và kiểm tra hạn mức."""
    engine = ReconciliationEngine(name_match_threshold=90.0, name_score_margin=5.0)
    entities = _make_sample_master_entities()
    fields = [
        _make_verified_field("party_b_tax_code", None, status=FieldStatus.NOT_PRESENT),
        _make_verified_field("party_b_name", "Công ty Cổ phần Bình Minh"),
        _make_verified_field("contract_value", "3.000.000.000 VND"),  # > 2 tỷ hạn mức Bình Minh
    ]

    items = engine.reconcile(fields, entities)
    assert any(item.error_type == "VALUE_OVER_LIMIT" for item in items)


def test_reconciliation_missing_tax_code_unknown_name():
    """Thiếu MST và tên không có trong DB -> NEEDS_HUMAN_REVIEW (không vội kết luận ENTITY_NOT_FOUND)."""
    engine = ReconciliationEngine(name_match_threshold=90.0, name_score_margin=5.0)
    entities = _make_sample_master_entities()
    fields = [
        _make_verified_field("party_b_tax_code", None, status=FieldStatus.NOT_PRESENT),
        _make_verified_field("party_b_name", "Công ty Chưa Đăng Ký Hệ Thống"),
    ]

    items = engine.reconcile(fields, entities)
    assert len(items) == 1
    assert items[0].error_type == "NEEDS_HUMAN_REVIEW"
    assert items[0].field_name == "party_b_name"


def test_reconciliation_unparseable_contract_value():
    """Giá trị hợp đồng chữ mơ hồ không thể chuyển thành số -> NEEDS_HUMAN_REVIEW."""
    engine = ReconciliationEngine(name_match_threshold=90.0, name_score_margin=5.0)
    entities = _make_sample_master_entities()
    fields = [
        _make_verified_field("party_b_tax_code", "0310000001"),
        _make_verified_field("party_b_name", "Công ty TNHH An Phát"),
        _make_verified_field("contract_value", "theo thỏa thuận từng đợt không cố định"),
    ]

    items = engine.reconcile(fields, entities)
    assert any(item.error_type == "NEEDS_HUMAN_REVIEW" and item.field_name == "contract_value" for item in items)


def test_reconciliation_ambiguous_company_names():
    """Hai ứng viên tên đạt ngưỡng và điểm sát nhau (chênh lệch <= NAME_SCORE_MARGIN) -> NEEDS_HUMAN_REVIEW."""
    engine = ReconciliationEngine(name_match_threshold=85.0, name_score_margin=5.0)
    # Tạo hai công ty có tên rất sát nhau
    entities = [
        SimpleNamespace(
            vat_code="0311111111",
            company_name="Công ty TNHH Sao Mai Việt",
            legal_representative="A",
            max_contract_value=Decimal("1000000000"),
        ),
        SimpleNamespace(
            vat_code="0322222222",
            company_name="Công ty TNHH Sao Mai",
            legal_representative="B",
            max_contract_value=Decimal("1000000000"),
        ),
    ]
    fields = [
        _make_verified_field("party_b_tax_code", "0399999999"),  # MST sai
        _make_verified_field("party_b_name", "Công ty TNHH Sao Mai"),
    ]

    items = engine.reconcile(fields, entities)
    assert len(items) == 1
    assert items[0].error_type == "NEEDS_HUMAN_REVIEW"
    assert items[0].field_name == "party_b_name"
    assert "sát nhau" in items[0].detail


def test_reconciliation_no_duplicate_review_items():
    """Không sinh trùng NEEDS_HUMAN_REVIEW nếu trường đã có trong existing_review_items."""
    engine = ReconciliationEngine(name_match_threshold=90.0, name_score_margin=5.0)
    entities = _make_sample_master_entities()
    fields = [
        _make_verified_field("party_b_tax_code", None, status=FieldStatus.NOT_PRESENT),
        _make_verified_field("party_b_name", "Công ty TNHH An Phát"),
        _make_verified_field("contract_value", "không xác định số tiền"),
    ]
    # Giả sử collect_review_items đã thêm sẵn review item cho contract_value
    existing_items = [
        AuditItem(
            error_type="NEEDS_HUMAN_REVIEW",
            field_name="contract_value",
            extracted_value="không xác định số tiền",
            expected_value=None,
            detail="Trường contract_value có vấn đề",
        )
    ]

    items = engine.reconcile(fields, entities, existing_review_items=existing_items)
    # Không được thêm một item NEEDS_HUMAN_REVIEW thứ hai cho contract_value
    val_reviews = [item for item in items if item.field_name == "contract_value" and item.error_type == "NEEDS_HUMAN_REVIEW"]
    assert len(val_reviews) == 0
