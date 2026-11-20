"""Giao diện Streamlit tối thiểu cho Hệ thống Thẩm định và Trích xuất Hợp đồng."""

import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# Bảo đảm import được gói `ui.*` khi chạy `streamlit run ui/streamlit_app.py` từ bất kỳ thư mục nào
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ui.api_client import (
    ApiClientError,
    check_api_health,
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


def _init_session_state() -> None:
    """Khởi tạo các khóa trạng thái phiên để tránh mất dữ liệu khi Streamlit rerun."""
    defaults = {
        "contract_id": None,
        "file_name": None,
        "audit_result": None,
        "ui_error": None,
        "timed_out": False,
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def _poll_until_finished(
    api_base_url: str,
    contract_id: int,
    poll_interval: float,
    poll_timeout: float,
) -> None:
    """Theo dõi trạng thái xử lý theo chu kỳ trong st.status cho tới DONE, FAILED hoặc timeout."""
    started_at = time.monotonic()
    st.session_state["timed_out"] = False
    st.session_state["ui_error"] = None

    with st.status(
        f"Đang xử lý hợp đồng #{contract_id}...",
        expanded=True,
        state="running",
    ) as status_box:
        st.write("Hệ thống đang phân tích tài liệu, gọi LLM trích xuất, kiểm chứng trích dẫn và đối soát dữ liệu.")
        while True:
            elapsed = time.monotonic() - started_at
            try:
                result = fetch_audit_result(api_base_url, contract_id, include_trace=True)
            except ApiClientError as error:
                st.session_state["ui_error"] = str(error)
                status_box.update(
                    label=f"Mất kết nối API khi theo dõi hợp đồng #{contract_id}",
                    state="error",
                    expanded=True,
                )
                return

            status = result.get("status")
            if status == "DONE":
                st.session_state["audit_result"] = result
                status_box.update(
                    label=f"Hoàn tất hợp đồng #{contract_id} sau {format_elapsed(elapsed)}.",
                    state="complete",
                    expanded=False,
                )
                return

            if status == "FAILED":
                st.session_state["audit_result"] = result
                err_msg = result.get("error_message") or "Quá trình xử lý thất bại không rõ nguyên nhân."
                st.session_state["ui_error"] = f"Xử lý hợp đồng #{contract_id} thất bại: {err_msg}"
                status_box.update(
                    label=f"Thất bại ở hợp đồng #{contract_id} sau {format_elapsed(elapsed)}",
                    state="error",
                    expanded=True,
                )
                return

            if elapsed >= poll_timeout:
                st.session_state["timed_out"] = True
                st.session_state["audit_result"] = result
                status_box.update(
                    label=f"Quá thời gian chờ ({format_elapsed(poll_timeout)}) cho hợp đồng #{contract_id}",
                    state="error",
                    expanded=True,
                )
                return

            status_box.update(
                label=f"Đang xử lý hợp đồng #{contract_id} (trạng thái: {status}, đã chờ {format_elapsed(elapsed)} / tối đa {format_elapsed(poll_timeout)})...",
                state="running",
                expanded=True,
            )
            time.sleep(poll_interval)


def _render_overall_banner(overall_result: str | None, contract_id: int, file_name: str | None, retry_count: int) -> None:
    """Hiển thị kết luận tổng thể nổi bật kèm thông tin hợp đồng và số lần retry."""
    meta = format_overall_result(overall_result)
    headline = f"**Kết luận tổng thể:** {meta['label']}\n\n{meta['description']}"
    severity = meta["severity"]
    if severity == "success":
        st.success(headline)
    elif severity == "warning":
        st.warning(headline)
    elif severity == "error":
        st.error(headline)
    else:
        st.info(headline)

    col1, col2, col3 = st.columns(3)
    col1.metric("Mã hợp đồng (contract_id)", str(contract_id))
    col2.metric("Tên tệp", file_name or "-")
    col3.metric("Số lần retry trích dẫn", str(retry_count))


def _render_results_section(result: dict, file_name: str | None) -> None:
    """Hiển thị bảng trường, cảnh báo đối soát, trích dẫn nguồn và trace_log."""
    contract_id = result.get("contract_id", st.session_state.get("contract_id"))
    retry_count = int(result.get("retry_count") or 0)

    st.divider()
    st.subheader("Kết quả thẩm định")

    _render_overall_banner(
        overall_result=result.get("overall_result"),
        contract_id=contract_id,
        file_name=file_name,
        retry_count=retry_count,
    )

    # 1. Bảng các trường trích xuất kèm trạng thái có nhãn chữ + tô màu
    st.markdown("### 1. Các trường thông tin trích xuất & kiểm chứng trích dẫn")
    fields = result.get("fields") or []
    if fields:
        rows = build_field_rows(fields)
        df = pd.DataFrame(rows)
        styled_df = df.style.map(get_status_cell_css, subset=["Trạng thái"])
        st.dataframe(styled_df, width="stretch", hide_index=True)
    else:
        st.info("Chưa có dữ liệu trường trích xuất.")

    # 2. Danh sách cảnh báo đối soát và kiểm tra thủ công
    st.markdown("### 2. Cảnh báo đối soát & yêu cầu kiểm tra (audit_items)")
    audit_items = result.get("audit_items") or []
    if audit_items:
        audit_rows = format_audit_items(audit_items)
        st.dataframe(pd.DataFrame(audit_rows), width="stretch", hide_index=True)
    else:
        st.success("Không có cảnh báo sai lệch hoặc trường cần rà soát thủ công.")

    # 3. Xem chi tiết quote nguồn từng trường
    st.markdown("### 3. Chi tiết bằng chứng nguồn (quote) theo từng trường")
    for field in fields:
        name = str(field.get("name") or "")
        status_meta = map_field_status(field.get("status"))
        score_text = format_match_score(field.get("match_score"))
        header = f"{format_field_name(name)} — {status_meta['label']} (Điểm khớp: {score_text})"
        with st.expander(header, expanded=False):
            c1, c2, c3 = st.columns(3)
            c1.write(f"**Giá trị:** {format_value(field.get('value'))}")
            c2.write(f"**Vị trí:** {format_location(field.get('page'), field.get('chunk_id'))}")
            c3.write(f"**Điểm khớp:** {score_text}")
            st.write("**Đoạn trích nguyên văn (quote):**")
            quote = field.get("quote")
            if quote:
                st.code(quote, language=None)
            else:
                st.caption("Không có trích dẫn nguồn.")

    # 4. Nhật ký thực thi agent (trace_log)
    st.markdown("### 4. Nhật ký thực thi LangGraph (trace_log)")
    trace_log = result.get("trace_log") or []
    with st.expander(f"Xem trace_log ({len(trace_log)} bước)", expanded=False):
        if trace_log:
            trace_df = pd.DataFrame(
                [
                    {
                        "Node": entry.get("node", "-"),
                        "Thời điểm": entry.get("ts", "-"),
                        "Tóm tắt": entry.get("summary", "-"),
                        "Quyết định": entry.get("decision", "-"),
                    }
                    for entry in trace_log
                ]
            )
            st.dataframe(trace_df, width="stretch", hide_index=True)
        else:
            st.caption("Không có dữ liệu trace_log.")


def main() -> None:
    st.set_page_config(
        page_title="Contract Verification Agent",
        layout="wide",
    )
    _init_session_state()

    api_base_url = get_api_base_url()
    poll_interval, poll_timeout = get_poll_config()

    st.title("Thẩm định & Trích xuất Thông tin Hợp đồng")
    st.caption(
        "Tải lên hợp đồng PDF (có lớp chữ) hoặc DOCX để trích xuất thông tin kèm trích dẫn nguồn, "
        "kiểm chứng bằng code thuần và đối soát dữ liệu đối tác."
    )

    with st.sidebar:
        st.subheader("Kết nối hệ thống")
        st.text(f"API: {api_base_url}")
        st.text(f"Timeout chờ: {int(poll_timeout)}s")
        if check_api_health(api_base_url):
            st.success("API đang hoạt động")
        else:
            st.error("API không phản hồi (/api/v1/healthz)")

    # Màn 1: Tải lên và kích hoạt xử lý
    st.subheader("Tải lên hợp đồng")
    uploaded_file = st.file_uploader(
        "Chọn tệp hợp đồng (.pdf hoặc .docx)",
        type=["pdf", "docx"],
        accept_multiple_files=False,
    )

    col_action, col_refresh = st.columns([2, 1])
    start_clicked = col_action.button(
        "Tải lên & Thẩm định",
        type="primary",
        disabled=uploaded_file is None,
    )
    refresh_clicked = col_refresh.button(
        "Kiểm tra lại kết quả",
        disabled=st.session_state.get("contract_id") is None,
    )

    if start_clicked and uploaded_file is not None:
        st.session_state["audit_result"] = None
        st.session_state["ui_error"] = None
        st.session_state["timed_out"] = False
        try:
            upload_resp = upload_contract_file(
                base_url=api_base_url,
                file_name=uploaded_file.name,
                content=uploaded_file.getvalue(),
                content_type=uploaded_file.type,
            )
            contract_id = int(upload_resp["contract_id"])
            st.session_state["contract_id"] = contract_id
            st.session_state["file_name"] = upload_resp.get("file_name") or uploaded_file.name

            trigger_audit_process(base_url=api_base_url, contract_id=contract_id)
            _poll_until_finished(api_base_url, contract_id, poll_interval, poll_timeout)
        except ApiClientError as error:
            st.session_state["ui_error"] = str(error)

    if refresh_clicked and st.session_state.get("contract_id") is not None:
        contract_id = int(st.session_state["contract_id"])
        st.session_state["ui_error"] = None
        try:
            latest = fetch_audit_result(api_base_url, contract_id, include_trace=True)
            st.session_state["audit_result"] = latest
            if latest.get("status") == "PROCESSING":
                _poll_until_finished(api_base_url, contract_id, poll_interval, poll_timeout)
            elif latest.get("status") == "FAILED":
                err_msg = latest.get("error_message") or "Xử lý thất bại."
                st.session_state["ui_error"] = f"Xử lý hợp đồng #{contract_id} thất bại: {err_msg}"
            else:
                st.session_state["timed_out"] = False
        except ApiClientError as error:
            st.session_state["ui_error"] = str(error)

    if st.session_state.get("ui_error"):
        st.error(st.session_state["ui_error"])

    if st.session_state.get("timed_out"):
        st.warning(
            f"Đã hết thời gian chờ ({format_elapsed(poll_timeout)}) nhưng backend có thể vẫn đang xử lý. "
            "Nhấn nút **Kiểm tra lại kết quả** để cập nhật mà không cần tải lại tệp."
        )

    result = st.session_state.get("audit_result")
    if result and result.get("status") == "DONE":
        _render_results_section(result, st.session_state.get("file_name"))


if __name__ == "__main__":
    main()
