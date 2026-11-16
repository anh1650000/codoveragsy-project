"""Kiểm thử toàn diện API FastAPI (/api/v1) bao gồm upload, process và result."""

import io
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.extraction.schema import ExtractedField, RawExtraction
from app.main import app


@pytest.fixture
def client():
    """Tạo TestClient cho ứng dụng FastAPI."""
    return TestClient(app)


def test_healthz_endpoints(client):
    """Cả /healthz gốc và /api/v1/healthz đều trả về status: ok."""
    resp1 = client.get("/healthz")
    assert resp1.status_code == 200
    assert resp1.json() == {"status": "ok"}

    resp2 = client.get("/api/v1/healthz")
    assert resp2.status_code == 200
    assert resp2.json() == {"status": "ok"}


def test_upload_invalid_extension(client):
    """File đuôi lạ (.txt) bị từ chối với mã HTTP 415."""
    fake_file = io.BytesIO(b"noi dung file text")
    response = client.post(
        "/api/v1/contracts/upload",
        files={"file": ("contract.txt", fake_file, "text/plain")},
    )
    assert response.status_code == 415
    assert "không được hỗ trợ" in response.json()["detail"]


def test_upload_invalid_content_type(client):
    """Content-Type không phù hợp (image/png) bị từ chối với 415."""
    fake_file = io.BytesIO(b"fake pdf content")
    response = client.post(
        "/api/v1/contracts/upload",
        files={"file": ("contract.pdf", fake_file, "image/png")},
    )
    assert response.status_code == 415


def test_upload_file_too_large(client, monkeypatch):
    """File vượt quá MAX_UPLOAD_MB bị từ chối với mã HTTP 413."""
    monkeypatch.setenv("MAX_UPLOAD_MB", "0.0001")  # Khoảng 100 bytes
    large_content = b"a" * 500
    fake_file = io.BytesIO(large_content)
    response = client.post(
        "/api/v1/contracts/upload",
        files={"file": ("contract.pdf", fake_file, "application/pdf")},
    )
    assert response.status_code == 413
    assert "vượt quá giới hạn" in response.json()["detail"]


def test_upload_valid_file(client):
    """Upload hợp đồng hợp lệ tạo bản ghi mới với status UPLOADED."""
    fake_file = io.BytesIO(b"%PDF-1.4 sample pdf content")
    response = client.post(
        "/api/v1/contracts/upload",
        files={"file": ("hop_dong_kinh_te.pdf", fake_file, "application/pdf")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["contract_id"] > 0
    assert data["file_name"] == "hop_dong_kinh_te.pdf"
    assert data["status"] == "UPLOADED"


def test_process_contract_not_found(client):
    """Gọi process với contract_id không tồn tại trả về 404."""
    response = client.post("/api/v1/audit/process/999999")
    assert response.status_code == 404
    assert "Không tìm thấy" in response.json()["detail"]


def test_result_contract_not_found(client):
    """Lấy kết quả với contract_id không tồn tại trả về 404."""
    response = client.get("/api/v1/audit/result/999999")
    assert response.status_code == 404
    assert "Không tìm thấy" in response.json()["detail"]


def test_process_ollama_unavailable(client):
    """Khi Ollama không phản hồi, process trả về mã 503 và cập nhật status=FAILED."""
    # 1. Upload một file hợp lệ
    fake_file = io.BytesIO(b"%PDF-1.4 sample")
    upload_res = client.post(
        "/api/v1/contracts/upload",
        files={"file": ("contract.pdf", fake_file, "application/pdf")},
    )
    contract_id = upload_res.json()["contract_id"]

    # 2. Mock Ollama trả về False (không phản hồi)
    with patch("app.api.routes.check_ollama_alive", return_value=False):
        process_res = client.post(f"/api/v1/audit/process/{contract_id}")
        assert process_res.status_code == 503
        assert "không khả dụng" in process_res.json()["detail"]

    # 3. Kiểm tra kết quả hợp đồng được đánh dấu FAILED
    result_res = client.get(f"/api/v1/audit/result/{contract_id}")
    assert result_res.status_code == 200
    assert result_res.json()["status"] == "FAILED"


def test_process_conflict_when_already_processing(client):
    """Không cho phép gọi process khi hợp đồng đang ở trạng thái PROCESSING (HTTP 409)."""
    fake_file = io.BytesIO(b"%PDF-1.4 sample")
    upload_res = client.post(
        "/api/v1/contracts/upload",
        files={"file": ("contract.pdf", fake_file, "application/pdf")},
    )
    contract_id = upload_res.json()["contract_id"]

    # Giả lập trạng thái hợp đồng đang PROCESSING
    from app.db.repository import ContractRepository
    from app.db.session import get_session_factory
    import asyncio

    async def _set_processing():
        factory = get_session_factory()
        async with factory() as session:
            repo = ContractRepository(session)
            await repo.update_status(contract_id, "PROCESSING")

    asyncio.run(_set_processing())

    # Gọi lại process -> phải nhận 409 Conflict
    response = client.post(f"/api/v1/audit/process/{contract_id}")
    assert response.status_code == 409
    assert "đang trong quá trình thẩm định" in response.json()["detail"]


def test_full_pipeline_upload_process_result(client, tmp_path):
    """Chạy toàn bộ luồng upload -> process -> result với graph mock xác định không dùng sleep."""
    # Chuẩn bị một file docx mẫu từ data/contracts nếu có, hoặc tạo file giả lập
    sample_file = Path("data/contracts/hd_001.pdf")
    if sample_file.exists():
        content = sample_file.read_bytes()
        file_name = "hd_001.pdf"
    else:
        content = b"%PDF-1.4 test contract"
        file_name = "test.pdf"

    upload_res = client.post(
        "/api/v1/contracts/upload",
        files={"file": (file_name, io.BytesIO(content), "application/pdf")},
    )
    assert upload_res.status_code == 201
    contract_id = upload_res.json()["contract_id"]

    # Mock extractor trả về kết quả An Phát (khớp hoàn toàn)
    clean_extraction = RawExtraction(
        party_a_name=ExtractedField(value="Công ty Cổ phần Alpha", quote="Bên A: Công ty Cổ phần Alpha"),
        party_b_name=ExtractedField(value="Công ty TNHH An Phát", quote="Bên B: Công ty TNHH An Phát"),
        party_b_tax_code=ExtractedField(value="0310000001", quote="Mã số thuế: 0310000001"),
        party_b_legal_representative=ExtractedField(value="Nguyễn Minh Anh", quote="Đại diện: Nguyễn Minh Anh"),
        contract_value=ExtractedField(value="500.000.000 đồng", quote="Giá trị: 500.000.000 đồng"),
        effective_date=ExtractedField(value="01/01/2026", quote="Ngày hiệu lực: 01/01/2026"),
        payment_terms=ExtractedField(value="Chuyển khoản", quote="Thanh toán: Chuyển khoản"),
    )

    mock_chunks = [
        {"chunk_id": 1, "page": 1, "text": "Bên A: Công ty Cổ phần Alpha. Bên B: Công ty TNHH An Phát. Mã số thuế: 0310000001. Đại diện: Nguyễn Minh Anh. Giá trị: 500.000.000 đồng. Ngày hiệu lực: 01/01/2026. Thanh toán: Chuyển khoản."}
    ]

    with patch("app.api.routes.check_ollama_alive", return_value=True), \
         patch("app.agent.nodes.parse_document", return_value=mock_chunks), \
         patch("app.agent.nodes.extract_fields", return_value=(clean_extraction, ["raw json"])):

        # POST /audit/process -> 202 Accepted và BackgroundTasks chạy tự động trong TestClient
        process_res = client.post(f"/api/v1/audit/process/{contract_id}")
        assert process_res.status_code == 202
        assert process_res.json()["status"] == "PROCESSING"

    # GET /audit/result -> Đã hoàn thành (DONE) và CLEAN
    result_res = client.get(f"/api/v1/audit/result/{contract_id}?include_trace=true")
    assert result_res.status_code == 200
    res_data = result_res.json()
    assert res_data["contract_id"] == contract_id
    assert res_data["status"] == "DONE"
    assert res_data["overall_result"] == "CLEAN"
    assert len(res_data["fields"]) == 7
    assert res_data["audit_items"] == []
    assert "trace_log" in res_data
    assert len(res_data["trace_log"]) > 0
