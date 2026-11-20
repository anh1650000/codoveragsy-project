"""Các hàm thuần xử lý cấu hình, định dạng nhãn/màu và dữ liệu hiển thị cho Streamlit UI."""

import os
from collections.abc import Sequence

DEFAULT_API_BASE_URL = "http://localhost:8000"
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_POLL_TIMEOUT_SECONDS = 600.0

FIELD_LABELS: dict[str, str] = {
    "party_a_name": "Tên Bên A",
    "party_b_name": "Tên Bên B (Đối tác)",
    "party_b_tax_code": "Mã số thuế Bên B",
    "party_b_legal_representative": "Người đại diện Bên B",
    "contract_value": "Giá trị hợp đồng",
    "effective_date": "Ngày hiệu lực",
    "payment_terms": "Điều khoản thanh toán",
}

OVERALL_RESULT_META: dict[str, dict[str, str]] = {
    "CLEAN": {
        "label": "CLEAN — Hợp lệ",
        "severity": "success",
        "description": "Các trường kiểm chứng đạt yêu cầu và khớp với dữ liệu đối tác trong hệ thống.",
    },
    "NEEDS_REVIEW": {
        "label": "NEEDS_REVIEW — Cần kiểm tra thủ công",
        "severity": "warning",
        "description": "Có trường bắt buộc bị thiếu hoặc chưa đạt kiểm chứng trích dẫn sau số lượt retry tối đa.",
    },
    "DISCREPANCY_FOUND": {
        "label": "DISCREPANCY_FOUND — Phát hiện sai lệch",
        "severity": "error",
        "description": "Phát hiện sai lệch thông tin đối tác hoặc vượt hạn mức hợp đồng khi đối soát.",
    },
}

FIELD_STATUS_META: dict[str, dict[str, str]] = {
    "VERIFIED": {
        "label": "VERIFIED (Đã xác minh)",
        "color": "green",
        "css": "background-color: #dcfce7; color: #166534; font-weight: 600;",
    },
    "QUOTE_NOT_FOUND": {
        "label": "QUOTE_NOT_FOUND (Không thấy trích dẫn)",
        "color": "red",
        "css": "background-color: #fee2e2; color: #991b1b; font-weight: 600;",
    },
    "VALUE_NOT_IN_QUOTE": {
        "label": "VALUE_NOT_IN_QUOTE (Giá trị không khớp trích dẫn)",
        "color": "red",
        "css": "background-color: #fee2e2; color: #991b1b; font-weight: 600;",
    },
    "NOT_PRESENT": {
        "label": "NOT_PRESENT (Không có trong tài liệu)",
        "color": "gray",
        "css": "background-color: #f3f4f6; color: #374151; font-weight: 500;",
    },
}

AUDIT_ERROR_LABELS: dict[str, str] = {
    "ENTITY_NOT_FOUND": "ENTITY_NOT_FOUND (Không tìm thấy đối tác)",
    "IDENTITY_MISMATCH": "IDENTITY_MISMATCH (Sai lệch định danh)",
    "VALUE_OVER_LIMIT": "VALUE_OVER_LIMIT (Vượt hạn mức hợp đồng)",
    "NEEDS_HUMAN_REVIEW": "NEEDS_HUMAN_REVIEW (Cần người kiểm tra)",
}


def get_api_base_url() -> str:
    """Đọc địa chỉ API từ biến môi trường API_BASE_URL."""
    raw = os.getenv("API_BASE_URL", DEFAULT_API_BASE_URL).strip()
    return raw.rstrip("/") if raw else DEFAULT_API_BASE_URL


def get_poll_config() -> tuple[float, float]:
    """Đọc khoảng nghỉ và ngưỡng timeout (giây) cho polling từ biến môi trường."""
    interval_raw = os.getenv("UI_POLL_INTERVAL_SECONDS", str(DEFAULT_POLL_INTERVAL_SECONDS))
    timeout_raw = os.getenv("UI_POLL_TIMEOUT_SECONDS", str(DEFAULT_POLL_TIMEOUT_SECONDS))
    try:
        interval = max(0.5, float(interval_raw))
    except ValueError:
        interval = DEFAULT_POLL_INTERVAL_SECONDS
    try:
        timeout = max(5.0, float(timeout_raw))
    except ValueError:
        timeout = DEFAULT_POLL_TIMEOUT_SECONDS
    return interval, timeout


def format_overall_result(overall_result: str | None) -> dict[str, str]:
    """Ánh xạ overall_result sang nhãn, mức độ cảnh báo và mô tả."""
    if not overall_result:
        return {
            "label": "CHƯA CÓ KẾT QUẢ",
            "severity": "info",
            "description": "Chưa có kết luận tổng thể từ hệ thống.",
        }
    return OVERALL_RESULT_META.get(
        overall_result,
        {
            "label": overall_result,
            "severity": "info",
            "description": "Trạng thái tổng thể từ API.",
        },
    )


def map_field_status(status: str | None) -> dict[str, str]:
    """Ánh xạ trạng thái field sang nhãn chữ đầy đủ, màu và style CSS."""
    if not status:
        return {
            "label": "UNKNOWN (Không xác định)",
            "color": "gray",
            "css": "background-color: #f3f4f6; color: #374151;",
        }
    return FIELD_STATUS_META.get(
        status,
        {
            "label": status,
            "color": "gray",
            "css": "background-color: #f3f4f6; color: #374151;",
        },
    )


def get_status_cell_css(status_label: object) -> str:
    """Trả về CSS tô màu ô dựa trên mã trạng thái nằm trong chuỗi nhãn."""
    text = str(status_label or "")
    for status_code, meta in FIELD_STATUS_META.items():
        if text.startswith(status_code):
            return meta["css"]
    return ""


def format_field_name(name: str) -> str:
    """Chuyển tên biến field sang nhãn tiếng Việt dễ đọc kèm tên gốc."""
    vi_label = FIELD_LABELS.get(name)
    if vi_label:
        return f"{vi_label} ({name})"
    return name


def format_value(value: object) -> str:
    """Định dạng giá trị hiển thị; giữ rõ ràng khi None hoặc rỗng."""
    if value is None:
        return "(Không có)"
    text = str(value).strip()
    return text if text else "(Không có)"


def format_match_score(score: float | int | None) -> str:
    """Định dạng điểm khớp quote theo phần trăm."""
    if score is None:
        return "-"
    return f"{float(score):.1f}%"


def format_location(page: int | None, chunk_id: int | None) -> str:
    """Hiển thị vị trí nguồn dựa trên số trang (PDF) và chunk_id."""
    parts: list[str] = []
    if page is not None:
        parts.append(f"Trang {page}")
    if chunk_id is not None:
        parts.append(f"Đoạn #{chunk_id}")
    return " | ".join(parts) if parts else "-"


def format_elapsed(seconds: float) -> str:
    """Định dạng thời gian đã trôi qua gọn gàng (giây hoặc phút:giây)."""
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, rem = divmod(total, 60)
    return f"{minutes}m {rem:02d}s"


def build_field_rows(fields: Sequence[dict]) -> list[dict[str, str]]:
    """Chuẩn bị danh sách dòng hiển thị bảng kết quả các trường trích xuất."""
    rows: list[dict[str, str]] = []
    for field in fields:
        name = str(field.get("name") or "")
        status = field.get("status")
        status_meta = map_field_status(str(status) if status is not None else None)
        rows.append(
            {
                "Trường": format_field_name(name),
                "Giá trị trích xuất": format_value(field.get("value")),
                "Trạng thái": status_meta["label"],
                "Điểm khớp": format_match_score(field.get("match_score")),
                "Vị trí": format_location(field.get("page"), field.get("chunk_id")),
            }
        )
    return rows


def format_audit_items(audit_items: Sequence[dict]) -> list[dict[str, str]]:
    """Chuẩn hóa danh sách cảnh báo audit_items để hiển thị rõ ràng trên UI."""
    formatted: list[dict[str, str]] = []
    for item in audit_items:
        error_type = str(item.get("error_type") or "")
        field_name = item.get("field_name")
        formatted.append(
            {
                "Loại cảnh báo": AUDIT_ERROR_LABELS.get(error_type, error_type or "-"),
                "Trường liên quan": format_field_name(str(field_name)) if field_name else "-",
                "Giá trị trong hợp đồng": format_value(item.get("extracted_value")),
                "Giá trị kỳ vọng": format_value(item.get("expected_value")),
                "Chi tiết": format_value(item.get("detail")),
            }
        )
    return formatted
