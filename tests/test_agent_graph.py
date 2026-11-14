import json
from types import SimpleNamespace

from app.agent.graph import build_contract_audit_graph, make_initial_state
from app.agent.nodes import AgentConfig
from app.extraction.extractor import extract_retry_fields
from app.extraction.schema import ExtractedField, FieldStatus, RawExtraction, VerifiedField
from app.llm.prompts import build_retry_extraction_messages


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
    return RawExtraction.model_validate(
        {
            name: ExtractedField(value=val, quote=quote)
            for name, (val, quote) in defaults.items()
        }
    )


def _stub_parser(_file_path: object) -> list[dict]:
    return _sample_chunks()


def test_graph_clean_extraction_finishes_without_retry():
    retry_calls = 0

    def mock_retry(_chunks, _failed):
        nonlocal retry_calls
        retry_calls += 1
        return {}

    graph = build_contract_audit_graph(
        parser=_stub_parser,
        extractor=lambda _chunks: _make_raw_extraction(),
        retry_extractor=mock_retry,
        config=AgentConfig(enable_verifier=True, enable_retry=True, max_retries=2),
    )

    result = graph.invoke(make_initial_state("dummy.pdf", contract_id=1))

    assert retry_calls == 0
    assert result["retry_count"] == 0
    assert result["audit_items"] == []
    assert result["overall_result"] == "CLEAN"
    assert all(vf.status == FieldStatus.VERIFIED for vf in result["verified_fields"])
    assert [entry["node"] for entry in result["trace_log"]] == [
        "parse_node",
        "extract_node",
        "verify_citation_node",
        "reconcile_db_node",
        "generate_report_node",
    ]
    assert result["report"]["overall_result"] == "CLEAN"


def test_graph_retries_single_failed_field_and_succeeds():
    retried_field_names: list[list[str]] = []

    def mock_retry(_chunks, failed_fields):
        retried_field_names.append([vf.name for vf in failed_fields])
        return {
            "contract_value": ExtractedField(
                value="500.000.000 đồng",
                quote="Giá trị hợp đồng: 500.000.000 đồng.",
            )
        }

    graph = build_contract_audit_graph(
        parser=_stub_parser,
        extractor=lambda _chunks: _make_raw_extraction(
            contract_value=("999.000.000 đồng", "Quote hoàn toàn bịa không có trong văn bản.")
        ),
        retry_extractor=mock_retry,
        config=AgentConfig(enable_verifier=True, enable_retry=True, max_retries=2),
    )

    result = graph.invoke(make_initial_state("dummy.pdf", contract_id=2))
    verified_map = {vf.name: vf for vf in result["verified_fields"]}

    assert retried_field_names == [["contract_value"]]
    assert result["retry_count"] == 1
    assert verified_map["contract_value"].status == FieldStatus.VERIFIED
    assert verified_map["contract_value"].page == 2
    assert result["audit_items"] == []
    assert result["overall_result"] == "CLEAN"
    assert [entry["node"] for entry in result["trace_log"]] == [
        "parse_node",
        "extract_node",
        "verify_citation_node",
        "retry_extraction_node",
        "verify_citation_node",
        "reconcile_db_node",
        "generate_report_node",
    ]


def test_graph_stops_at_max_retries_and_marks_needs_human_review():
    retry_calls = 0

    def mock_retry(_chunks, _failed_fields):
        nonlocal retry_calls
        retry_calls += 1
        return {
            "contract_value": ExtractedField(
                value="999.000.000 đồng",
                quote="Vẫn là quote bịa đặt không tồn tại.",
            )
        }

    graph = build_contract_audit_graph(
        parser=_stub_parser,
        extractor=lambda _chunks: _make_raw_extraction(
            contract_value=("888.000.000 đồng", "Quote bịa lần đầu.")
        ),
        retry_extractor=mock_retry,
        config=AgentConfig(enable_verifier=True, enable_retry=True, max_retries=2),
    )

    result = graph.invoke(make_initial_state("dummy.pdf", contract_id=3))

    assert retry_calls == 2
    assert result["retry_count"] == 2
    assert result["overall_result"] == "NEEDS_REVIEW"
    assert len(result["audit_items"]) == 1
    assert result["audit_items"][0].error_type == "NEEDS_HUMAN_REVIEW"
    assert result["audit_items"][0].field_name == "contract_value"


def test_graph_flags_missing_required_field_not_present_as_needs_human_review():
    retry_calls = 0

    def mock_retry(_chunks, _failed_fields):
        nonlocal retry_calls
        retry_calls += 1
        return {}

    graph = build_contract_audit_graph(
        parser=_stub_parser,
        extractor=lambda _chunks: _make_raw_extraction(
            party_b_tax_code=(None, None),
            payment_terms=(None, None),
        ),
        retry_extractor=mock_retry,
        config=AgentConfig(enable_verifier=True, enable_retry=True, max_retries=2),
    )

    result = graph.invoke(make_initial_state("dummy.pdf", contract_id=4))

    assert retry_calls == 0
    assert result["retry_count"] == 0
    assert result["overall_result"] == "NEEDS_REVIEW"
    assert len(result["audit_items"]) == 1
    assert result["audit_items"][0].error_type == "NEEDS_HUMAN_REVIEW"
    assert result["audit_items"][0].field_name == "party_b_tax_code"


def test_graph_skips_retry_when_enable_retry_is_false():
    retry_calls = 0

    def mock_retry(_chunks, _failed_fields):
        nonlocal retry_calls
        retry_calls += 1
        return {}

    graph = build_contract_audit_graph(
        parser=_stub_parser,
        extractor=lambda _chunks: _make_raw_extraction(
            contract_value=("900.000.000 đồng", "Giá trị hợp đồng: 500.000.000 đồng.")
        ),
        retry_extractor=mock_retry,
        config=AgentConfig(enable_verifier=True, enable_retry=False, max_retries=2),
    )

    result = graph.invoke(make_initial_state("dummy.pdf", contract_id=5))
    verified_map = {vf.name: vf for vf in result["verified_fields"]}

    assert retry_calls == 0
    assert result["retry_count"] == 0
    assert verified_map["contract_value"].status == FieldStatus.VALUE_NOT_IN_QUOTE
    assert result["overall_result"] == "NEEDS_REVIEW"
    assert [item.field_name for item in result["audit_items"]] == ["contract_value"]


def test_graph_bypasses_verifier_when_enable_verifier_is_false():
    retry_calls = 0

    def mock_retry(_chunks, _failed_fields):
        nonlocal retry_calls
        retry_calls += 1
        return {}

    # Cố tình đưa vào quote bịa + giá trị sai để kiểm tra ablation khi tắt verifier:
    # các field có giá trị vẫn đi qua dưới dạng VERIFIED giả lập, còn field bắt buộc None vẫn NEEDS_HUMAN_REVIEW.
    graph = build_contract_audit_graph(
        parser=_stub_parser,
        extractor=lambda _chunks: _make_raw_extraction(
            party_b_name=("Công ty Bịa Đặt", "Quote không có trong tài liệu."),
            contract_value=("9.999.999.999 đồng", "Giá trị hợp đồng: 500.000.000 đồng."),
            party_b_tax_code=(None, None),
        ),
        retry_extractor=mock_retry,
        config=AgentConfig(enable_verifier=False, enable_retry=True, max_retries=2),
    )

    result = graph.invoke(make_initial_state("dummy.pdf", contract_id=6))
    verified_map = {vf.name: vf for vf in result["verified_fields"]}

    assert retry_calls == 0
    assert result["retry_count"] == 0
    assert verified_map["party_b_name"].status == FieldStatus.VERIFIED
    assert verified_map["party_b_name"].match_score is None
    assert verified_map["party_b_name"].page is None
    assert verified_map["party_b_name"].chunk_id is None
    assert verified_map["contract_value"].status == FieldStatus.VERIFIED
    assert verified_map["party_b_tax_code"].status == FieldStatus.NOT_PRESENT
    assert [item.field_name for item in result["audit_items"]] == ["party_b_tax_code"]
    assert result["overall_result"] == "NEEDS_REVIEW"


def test_graph_does_not_overwrite_verified_fields_when_retrying_other_fields():
    def mock_retry(_chunks, _failed_fields):
        # Mock cố tình trả kèm cả party_b_name đã VERIFIED với nội dung bị sửa;
        # retry_extraction_node phải bỏ qua field không lỗi để bảo toàn dữ liệu đã kiểm chứng.
        return {
            "party_b_name": ExtractedField(
                value="Công ty Bị Ghi Đè",
                quote="Quote bịa",
            ),
            "contract_value": ExtractedField(
                value="500.000.000 đồng",
                quote="Giá trị hợp đồng: 500.000.000 đồng.",
            ),
        }

    graph = build_contract_audit_graph(
        parser=_stub_parser,
        extractor=lambda _chunks: _make_raw_extraction(
            contract_value=("123.000.000 đồng", "Quote sai hoàn toàn.")
        ),
        retry_extractor=mock_retry,
        config=AgentConfig(enable_verifier=True, enable_retry=True, max_retries=2),
    )

    result = graph.invoke(make_initial_state("dummy.pdf", contract_id=7))
    verified_map = {vf.name: vf for vf in result["verified_fields"]}

    assert verified_map["party_b_name"].status == FieldStatus.VERIFIED
    assert verified_map["party_b_name"].value == "Công ty TNHH An Phát"
    assert verified_map["contract_value"].status == FieldStatus.VERIFIED
    assert result["overall_result"] == "CLEAN"


def test_retry_prompt_and_extract_retry_fields_validate_only_failed_fields():
    failed = [
        VerifiedField(
            name="party_b_tax_code",
            value="0310000001",
            quote="Quote bịa",
            status=FieldStatus.QUOTE_NOT_FOUND,
            match_score=20.0,
            page=None,
            chunk_id=None,
        ),
        VerifiedField(
            name="contract_value",
            value="900.000.000 đồng",
            quote="Giá trị hợp đồng: 500.000.000 đồng.",
            status=FieldStatus.VALUE_NOT_IN_QUOTE,
            match_score=100.0,
            page=2,
            chunk_id=6,
        ),
    ]
    messages = build_retry_extraction_messages(_sample_chunks(), failed)
    user_content = messages[1]["content"]
    assert "quote bạn đưa không xuất hiện trong tài liệu" in user_content
    assert "giá trị không nằm trong quote" in user_content
    assert "null" in user_content
    assert "party_b_name" not in user_content

    responses = iter(
        [
            "not-json",
            json.dumps(
                {
                    "party_b_tax_code": None,
                    "contract_value": {
                        "value": "500.000.000 đồng",
                        "quote": "Giá trị hợp đồng: 500.000.000 đồng.",
                    },
                },
                ensure_ascii=False,
            ),
        ]
    )

    class _FakeCompletions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=next(responses)))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
    retried, raw_outputs = extract_retry_fields(
        _sample_chunks(),
        failed,
        client=fake_client,
        model="mock-model",
        max_retries=1,
    )

    assert len(raw_outputs) == 2
    assert retried["party_b_tax_code"] == ExtractedField(value=None, quote=None)
    assert retried["contract_value"].value == "500.000.000 đồng"
