"""Unit test cho các hàm thuần và HTTP client mỏng của Streamlit UI."""

import httpx
import pytest

from ui.api_client import (
    ApiClientError,
    fetch_audit_result,
    trigger_audit_process,
    upload_contract_file,
)
from ui.formatters import (
    build_field_rows,
    format_audit_items,
    format_elapsed,
    format_field_name,
    format_location,
    format_match_score,
    format_overall_result,
    format_value,
    get_api_base_url,
    get_poll_config,
    get_status_cell_css,
    map_field_status,
)


def test_map_field_status_keeps_text_and_expected_colors():
    verified = map_field_status("VERIFIED")
    assert verified["color"] == "green"
    assert "VERIFIED" in verified["label"]
    assert "#dcfce7" in get_status_cell_css(verified["label"])

    qnf = map_field_status("QUOTE_NOT_FOUND")
    assert qnf["color"] == "red"
    assert "QUOTE_NOT_FOUND" in qnf["label"]
    assert "#fee2e2" in get_status_cell_css(qnf["label"])

    vniq = map_field_status("VALUE_NOT_IN_QUOTE")
    assert vniq["color"] == "red"
    assert "VALUE_NOT_IN_QUOTE" in vniq["label"]
    assert "#fee2e2" in get_status_cell_css(vniq["label"])

    absent = map_field_status("NOT_PRESENT")
    assert absent["color"] == "gray"
    assert "NOT_PRESENT" in absent["label"]
    assert "#f3f4f6" in get_status_cell_css(absent["label"])


def test_format_overall_result_maps_all_known_states():
    assert format_overall_result("CLEAN")["severity"] == "success"
    assert format_overall_result("NEEDS_REVIEW")["severity"] == "warning"
    assert format_overall_result("DISCREPANCY_FOUND")["severity"] == "error"
    assert format_overall_result(None)["severity"] == "info"


def test_formatting_helpers_handle_none_and_numbers():
    assert format_value(None) == "(Không có)"
    assert format_value("  ") == "(Không có)"
    assert format_value("0310000001") == "0310000001"

    assert format_match_score(None) == "-"
    assert format_match_score(96.45) == "96.5%"

    assert format_location(1, 4) == "Trang 1 | Đoạn #4"
    assert format_location(None, 4) == "Đoạn #4"
    assert format_location(None, None) == "-"

    assert format_elapsed(45) == "45s"
    assert format_elapsed(125) == "2m 05s"
    assert "party_b_tax_code" in format_field_name("party_b_tax_code")


def test_build_field_rows_and_format_audit_items():
    rows = build_field_rows(
        [
            {
                "name": "party_b_tax_code",
                "value": "0310000001",
                "status": "VERIFIED",
                "match_score": 100.0,
                "page": 1,
                "chunk_id": 4,
            }
        ]
    )
    assert len(rows) == 1
    assert rows[0]["Giá trị trích xuất"] == "0310000001"
    assert "VERIFIED" in rows[0]["Trạng thái"]
    assert rows[0]["Điểm khớp"] == "100.0%"
    assert rows[0]["Vị trí"] == "Trang 1 | Đoạn #4"

    audit_rows = format_audit_items(
        [
            {
                "error_type": "IDENTITY_MISMATCH",
                "field_name": "party_b_tax_code",
                "extracted_value": "0390000003",
                "expected_value": "0310000003",
                "detail": "MST không khớp",
            }
        ]
    )
    assert len(audit_rows) == 1
    assert "IDENTITY_MISMATCH" in audit_rows[0]["Loại cảnh báo"]
    assert audit_rows[0]["Giá trị trong hợp đồng"] == "0390000003"
    assert audit_rows[0]["Giá trị kỳ vọng"] == "0310000003"


def test_env_helpers_read_configuration(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "http://api:8000/")
    monkeypatch.setenv("UI_POLL_INTERVAL_SECONDS", "3")
    monkeypatch.setenv("UI_POLL_TIMEOUT_SECONDS", "900")
    assert get_api_base_url() == "http://api:8000"
    assert get_poll_config() == (3.0, 900.0)


def test_api_client_upload_process_result_with_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/contracts/upload":
            return httpx.Response(
                201,
                json={"contract_id": 12, "file_name": "hd_001.pdf", "status": "UPLOADED"},
            )
        if request.url.path == "/api/v1/audit/process/12":
            return httpx.Response(202, json={"contract_id": 12, "status": "PROCESSING"})
        if request.url.path == "/api/v1/audit/result/12":
            assert request.url.params["include_trace"] == "true"
            return httpx.Response(
                200,
                json={"contract_id": 12, "status": "DONE", "overall_result": "CLEAN", "fields": [], "audit_items": [], "retry_count": 0, "trace_log": []},
            )
        return httpx.Response(404, json={"detail": "Not found"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    uploaded = upload_contract_file("http://api:8000", "hd_001.pdf", b"%PDF", client=client)
    assert uploaded["contract_id"] == 12

    started = trigger_audit_process("http://api:8000", 12, client=client)
    assert started["status"] == "PROCESSING"

    result = fetch_audit_result("http://api:8000", 12, include_trace=True, client=client)
    assert result["overall_result"] == "CLEAN"


def test_api_client_raises_clear_error_on_http_failure():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "Dịch vụ LLM Ollama không khả dụng."})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ApiClientError, match="Ollama không khả dụng"):
        trigger_audit_process("http://api:8000", 1, client=client)
