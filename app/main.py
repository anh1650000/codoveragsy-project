"""Điểm khởi chạy ứng dụng FastAPI cho hệ thống thẩm định hợp đồng."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router

app = FastAPI(
    title="Contract & Document Verification Agent API",
    description="Hệ thống tự động hóa thẩm định và trích xuất thông tin hợp đồng kèm kiểm chứng trích dẫn nguồn và đối soát cơ sở dữ liệu.",
    version="1.0.0",
)

# Cấu hình CORS để cho phép Streamlit UI hoặc client web kết nối
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gắn router API với prefix /api/v1
app.include_router(api_router)


@app.get("/healthz", tags=["Health"])
async def root_healthz() -> dict:
    """Health check endpoint ở đường dẫn gốc theo đặc tả mục 10."""
    return {"status": "ok"}
