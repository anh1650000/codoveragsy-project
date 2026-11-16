"""Định nghĩa các API endpoint /api/v1 cho tải lên, thẩm định và tra cứu hợp đồng."""

import asyncio
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_contract_audit_graph, make_initial_state
from app.api.deps import get_db_session
from app.core.config import get_setting
from app.db.repository import ContractRepository
from app.db.session import get_session_factory

router = APIRouter(prefix="/api/v1")

ALLOWED_EXTENSIONS = {".pdf", ".docx"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/octet-stream",
    "application/x-zip-compressed",
}


async def check_ollama_alive(timeout_seconds: float = 1.5) -> bool:
    """Kiểm tra nhanh xem dịch vụ Ollama có đang hoạt động hay không."""
    base_url = get_setting("LLM_BASE_URL", "http://localhost:11434/v1")
    url = f"{base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.get(url)
            return response.status_code == 200
    except Exception:
        return False


async def run_audit_pipeline(contract_id: int) -> None:
    """Hàm chạy nền cho LangGraph pipeline. Tự tạo AsyncSession riêng để không chia sẻ với request."""
    factory = get_session_factory()
    async with factory() as session:
        repo = ContractRepository(session)
        contract = await repo.get_contract(contract_id)
        if contract is None:
            return

        try:
            # Lấy danh sách master_entities từ DB để truyền cho graph đối soát
            master_entities = await repo.get_all_master_entities()
            graph = build_contract_audit_graph(master_entities=master_entities)
            initial_state = make_initial_state(contract.file_path, contract_id=contract_id)

            # Chạy graph trong thread pool để tránh block event loop của FastAPI
            final_state = await asyncio.to_thread(graph.invoke, initial_state)

            verified_fields = [
                vf.model_dump(mode="json")
                for vf in final_state.get("verified_fields", [])
            ]
            audit_items = [
                item.model_dump(mode="json")
                for item in final_state.get("audit_items", [])
            ]
            trace_log = final_state.get("trace_log", [])
            overall_result = final_state.get("overall_result") or "CLEAN"
            retry_count = final_state.get("retry_count", 0)

            await repo.save_audit_results(
                contract_id=contract_id,
                overall_result=overall_result,
                verified_fields=verified_fields,
                audit_items=audit_items,
                retry_count=retry_count,
                trace_log=trace_log,
                error_message=None,
            )
        except Exception as error:
            # Không nuốt lỗi: cập nhật status=FAILED kèm nội dung lỗi cụ thể
            await repo.update_status(
                contract_id=contract_id,
                status="FAILED",
                error_message=f"{type(error).__name__}: {error}",
            )


@router.post("/contracts/upload", status_code=status.HTTP_201_CREATED)
async def upload_contract(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Tải lên file hợp đồng PDF hoặc DOCX, kiểm tra hợp lệ và lưu vào kho lưu trữ."""
    original_name = file.filename or "unknown"
    ext = Path(original_name).suffix.lower()

    # 1. Kiểm tra định dạng đuôi file
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Định dạng file '{ext}' không được hỗ trợ. Chỉ chấp nhận .pdf và .docx",
        )

    # 2. Kiểm tra content-type nếu client có gửi
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Content-Type '{file.content_type}' không hợp lệ cho hợp đồng.",
        )

    # 3. Đọc dữ liệu và kiểm tra giới hạn dung lượng
    max_mb_raw = get_setting("MAX_UPLOAD_MB", "10")
    try:
        max_mb = float(max_mb_raw)
    except ValueError:
        max_mb = 10.0
    max_bytes = int(max_mb * 1024 * 1024)

    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Dung lượng file vượt quá giới hạn cho phép ({max_mb} MB).",
        )

    # 4. Lưu file dưới tên ngẫu nhiên UUID để chống path traversal
    upload_dir_raw = get_setting("UPLOAD_DIR", "./data/uploads")
    upload_dir = Path(upload_dir_raw)
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = f"{uuid4().hex}{ext}"
    saved_path = upload_dir / safe_name
    saved_path.write_bytes(content)

    # 5. Lưu bản ghi contracts vào cơ sở dữ liệu
    repo = ContractRepository(session)
    contract = await repo.create_contract(
        file_name=original_name,
        file_path=str(saved_path.resolve()),
    )

    return {
        "contract_id": contract.id,
        "file_name": contract.file_name,
        "status": contract.status,
    }


@router.post("/audit/process/{contract_id}", status_code=status.HTTP_202_ACCEPTED)
async def process_contract(
    contract_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Kích hoạt quy trình thẩm định hợp đồng ở chế độ nền (BackgroundTasks)."""
    repo = ContractRepository(session)
    contract = await repo.get_contract(contract_id)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy hợp đồng với ID {contract_id}.",
        )

    # Chống chạy trùng khi đang PROCESSING
    if contract.status == "PROCESSING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hợp đồng đang trong quá trình thẩm định. Vui lòng chờ hoàn tất.",
        )

    # Nếu hợp đồng đã DONE hoặc FAILED: dọn kết quả cũ để chạy lại
    if contract.status in {"DONE", "FAILED"}:
        await repo.reset_for_reprocess(contract_id)
    else:
        await repo.update_status(contract_id, "PROCESSING")

    # Kiểm tra nhanh trạng thái sẵn sàng của dịch vụ Ollama trước khi nhận việc
    is_alive = await check_ollama_alive()
    if not is_alive:
        await repo.update_status(
            contract_id,
            status="FAILED",
            error_message="Dịch vụ LLM Ollama không phản hồi khi kích hoạt xử lý.",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dịch vụ LLM Ollama không khả dụng. Vui lòng kiểm tra Ollama trên máy chủ.",
        )

    # Đưa tác vụ vào chạy nền với session độc lập
    background_tasks.add_task(run_audit_pipeline, contract_id)

    return {
        "contract_id": contract_id,
        "status": "PROCESSING",
        "message": "Yêu cầu thẩm định đã được tiếp nhận và đang xử lý ở chế độ nền.",
    }


@router.get("/audit/result/{contract_id}")
async def get_audit_result(
    contract_id: int,
    include_trace: bool = Query(default=False, description="Kèm lịch sử từng bước thực thi trace_log"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Tra cứu kết quả thẩm định và các cảnh báo sai lệch của hợp đồng."""
    repo = ContractRepository(session)
    details = await repo.get_contract_with_details(contract_id)
    if details is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy hợp đồng với ID {contract_id}.",
        )

    result = {
        "contract_id": details["contract_id"],
        "status": details["status"],
        "overall_result": details["overall_result"],
        "fields": details["fields"],
        "audit_items": details["audit_items"],
        "retry_count": details["retry_count"],
        "error_message": details["error_message"],
        "completed_at": details["completed_at"],
    }
    if include_trace:
        result["trace_log"] = details["trace_log"]

    return result


@router.get("/healthz")
async def health_check() -> dict:
    """Health check endpoint cho giám sát hệ thống."""
    return {"status": "ok"}
