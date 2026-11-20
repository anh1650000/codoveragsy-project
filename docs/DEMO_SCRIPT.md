# Kịch bản Video Demo (2–3 phút)

Tài liệu này dùng để quay video giới thiệu và chạy thử toàn hệ thống thông qua giao diện Streamlit (`http://localhost:8501`).

---

## Chuẩn bị trước khi bấm quay

1. Khởi động sẵn toàn bộ stack bằng Docker Compose:
   ```bash
   docker compose up --build
   ```
2. Kiểm tra API khỏe mạnh và model Ollama đã nạp sẵn trên máy để giảm thời gian chờ cold-start ở lần gọi đầu tiên:
   ```bash
   python scripts/smoke_test.py --file data/contracts/hd_001.pdf
   ```
3. Chuẩn bị sẵn 3 file mẫu trong `data/contracts/`:
   - **File sạch (`CLEAN`):** `data/contracts/hd_001.pdf`
   - **File sai mã số thuế (`WRONG_TAX_CODE`):** `data/contracts/hd_003.pdf`
   - **File thiếu trường bắt buộc (`MISSING_FIELD`):** `data/contracts/hd_011.pdf`

> **Mẹo xử lý thời gian chờ model chậm (laptop 4 GB VRAM):**
> - **Cách 1 (khuyên dùng):** Nạp sẵn model trước khi quay, bấm chạy trên UI, nói phần giới thiệu ngắn trong 5–10 giây rồi **cắt/tua nhanh (jump cut / speed-up)** đoạn chờ polling, giữ lại lúc chuyển trạng thái sang `DONE`.
> - **Cách 2:** Chạy trước 1–2 file vào tab/cửa sổ khác hoặc giữ ảnh kết quả để đối chiếu nếu muốn giữ video đúng 2–3 phút mà không bị khoảng lặng chờ LLM.

---

## Dàn ý từng cảnh quay

### Cảnh 1: Giới thiệu bài toán & kiến trúc (0:00 – 0:30)
- **Thao tác màn hình:** Hiện màn hình chính Streamlit (`http://localhost:8501`) hoặc sơ đồ kiến trúc trong `README.md`.
- **Lời dẫn ngắn:**
  > "Đây là hệ thống tự động đọc hợp đồng PDF/DOCX, trích xuất thông tin quan trọng bằng LLM chạy cục bộ qua Ollama, kiểm chứng trích dẫn bằng code thuần để chống ảo giác và đối soát thông tin đối tác Bên B với PostgreSQL."
- **Ý chính cần nêu (tự diễn đạt theo ý bạn):**
  - Mọi giá trị trích xuất đều phải kèm đoạn nguyên văn (`quote`) và được kiểm chứng hai lớp bằng code (`quote` có tồn tại + `value` có nằm trong đoạn khớp).
  - Giao diện Streamlit chỉ là client mỏng gọi FastAPI qua HTTP.

### Cảnh 2: Ca 1 — Hợp đồng sạch (`hd_001.pdf` → `CLEAN`) (0:30 – 1:15)
- **Thao tác màn hình:**
  1. Chọn `hd_001.pdf` trong `st.file_uploader`.
  2. Bấm **Tải lên & Thẩm định** (cắt/tua nhanh phần chờ polling trong `st.status`).
  3. Khi ra kết quả `CLEAN`: chỉ vào bảng 7 trường đều mang nhãn xanh `VERIFIED`.
  4. Mở 1–2 expander (ví dụ `party_b_tax_code`, `contract_value`) để cho thấy đoạn `quote`, số trang (`Trang 1`) và `match_score`.
- **Lời dẫn ngắn:**
  > "Với hợp đồng chuẩn `hd_001.pdf`, tất cả các trường đều được xác minh có trích dẫn hợp lệ trong văn bản gốc và khớp hoàn toàn với dữ liệu đối tác trong PostgreSQL, trả về kết luận `CLEAN`."

### Cảnh 3: Ca 2 — Hợp đồng sai mã số thuế (`hd_003.pdf` → `DISCREPANCY_FOUND`) (1:15 – 2:00)
- **Thao tác màn hình:**
  1. Chọn `hd_003.pdf` và bấm **Tải lên & Thẩm định** (cắt/tua đoạn chờ).
  2. Khi ra kết quả `DISCREPANCY_FOUND`: chỉ vào phần **Cảnh báo đối soát (`audit_items`)** hiển thị `IDENTITY_MISMATCH` (giá trị trong hợp đồng `0390000003` vs giá trị kỳ vọng `0310000003` của Công ty TNHH Cửu Long).
  3. Mở expander của `party_b_tax_code` để nhấn mạnh: trích xuất & trích dẫn đúng với hợp đồng (`VERIFIED`), nhưng bước đối soát nghiệp vụ bằng code phát hiện sai lệch với DB.
- **Lời dẫn ngắn:**
  > "Ở `hd_003.pdf`, LLM trích xuất đúng những gì ghi trên giấy (`VERIFIED`), nhưng engine đối soát phát hiện tên công ty khớp trong hệ thống mà mã số thuế lại khác, nên đánh dấu `DISCREPANCY_FOUND`."

### Cảnh 4: Ca 3 — Hợp đồng thiếu trường bắt buộc (`hd_011.pdf` → `NEEDS_REVIEW`) & Trace log (2:00 – 2:45)
- **Thao tác màn hình:**
  1. Chọn `hd_011.pdf` và bấm **Tải lên & Thẩm định** (cắt/tua đoạn chờ).
  2. Khi ra kết quả `NEEDS_REVIEW`: chỉ vào dòng `party_b_tax_code` có nhãn xám `NOT_PRESENT` và cảnh báo `NEEDS_HUMAN_REVIEW`.
  3. Mở expander **Nhật ký thực thi LangGraph (`trace_log`)** ở cuối trang để cho thấy các bước graph đã đi qua (`parse_node` → `extract_node` → `verify_citation_node` → `reconcile_db_node` → `generate_report_node`) và `retry_count`.
- **Lời dẫn ngắn:**
  > "Với `hd_011.pdf` bị khuyết mã số thuế, hệ thống không tự suy đoán giá trị mà giữ trạng thái `NOT_PRESENT` và chuyển `NEEDS_REVIEW` cho người kiểm tra. Cuối trang là `trace_log` ghi lại toàn bộ quyết định rẽ nhánh của agent."

### Cảnh 5: Kết thúc ngắn (2:45 – 3:00)
- **Thao tác màn hình:** Quay lại tổng quan `docker compose ps` hoặc `README.md`.
- **Ý chính cần nêu (tự diễn đạt theo ý bạn):**
  - Toàn bộ stack đóng gói gọn bằng Docker Compose (PostgreSQL, API, UI) kết nối Ollama local; mã nguồn kèm bộ test `pytest`.
