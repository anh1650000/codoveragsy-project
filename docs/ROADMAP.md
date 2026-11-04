# LỘ TRÌNH TRIỂN KHAI NIÊN LUẬN 8 TUẦN (BẢN CHỈNH SỬA)

## Đề tài: Hệ thống Agent Tự động hóa Thẩm định và Trích xuất Thông tin Hợp đồng/Hồ sơ
**Tên tiếng Anh:** Contract & Document Verification Agent System
**Công nghệ chính:** Python, LangGraph, Qwen (Ollama chạy trên máy chính), FastAPI, PostgreSQL, RapidFuzz, Streamlit, Docker.

---

## 0. Những điểm đã chỉnh so với bản gốc

| # | Vấn đề ở bản gốc | Cách sửa |
|---|---|---|
| 1 | Làm theo từng lớp (parse → verify → agent → API), tới tuần 6 mới có hệ thống chạy được end-to-end. Nếu trễ 1-2 tuần thì không có gì để demo hoặc đưa vào CV. | Chạy được bản end-to-end mỏng (CLI) ngay từ tuần 2, sau đó mới làm dày dần từng phần. |
| 2 | Citation check chỉ kiểm tra `quote` có tồn tại trong văn bản gốc. LLM vẫn có thể trích dẫn đúng câu nhưng điền sai giá trị (vd quote nói 500 triệu, field ghi 5 tỷ). | Thêm bước **value-in-quote**: giá trị đã chuẩn hóa phải xuất hiện trong chính đoạn `quote`. |
| 3 | Bắt LLM tự trả số trang (`page`). LLM đoán số trang rất kém, và DOCX không có khái niệm trang cố định. | Số trang/vị trí do **code tính** từ vị trí khớp của quote trong văn bản. DOCX dùng chỉ số đoạn (paragraph index). |
| 4 | Bộ dữ liệu test (10 hợp đồng) để đến tuần 7 mới làm, trong khi cần từ tuần 2 để chỉnh prompt. Chỉ tiêu "≥95% phát hiện ảo giác" đặt ra trước khi đo, với 10 mẫu thì không có ý nghĩa thống kê. | Làm bộ dữ liệu ngay tuần 1 (hợp đồng + ground truth). Mở rộng lên 25-30 mẫu. Không đặt chỉ tiêu cứng, báo cáo số đo thật và làm **ablation** (có/không verifier, có/không retry). |
| 5 | Tuần 8 gồm UI + báo cáo 5 chương + slide, quá tải. Không có test, không có trace log (đã có trong spec ban đầu). | Viết báo cáo dần từng chương theo tuần. UI làm bản tối thiểu ở tuần 6. Bổ sung pytest và trace log vào các tuần tương ứng. |

---

## 1. Bảng Tổng quan Lộ trình

| Tuần | Giai đoạn | Mục tiêu chính | Đầu ra |
| :---: | :--- | :--- | :--- |
| **1** | Nền tảng + dữ liệu | Docker, schema, bộ hợp đồng mẫu có ground truth, kiểm tra phần cứng chạy LLM | `docker-compose.yml`, schema, `master_entities` seed, 12-15 hợp đồng mẫu + JSON đáp án |
| **2** | Parse + Extraction + bản end-to-end mỏng | Đọc PDF/DOCX, trích xuất JSON kèm quote, chạy thử trên bộ mẫu | Parser, Pydantic schema, prompt, script CLI chạy được, số đo baseline |
| **3** | Anti-Hallucination Core | Kiểm tra quote tồn tại + value-in-quote | `CitationVerifier`, unit test |
| **4** | Agent với LangGraph | State machine, retry có giới hạn, trace log | StateGraph chạy end-to-end, `trace_log` |
| **5** | Reconciliation + API | Đối soát với Postgres, API async | `ReconciliationEngine`, `audit_logs`, FastAPI 3 endpoint |
| **6** | UI tối thiểu + bản "đưa vào CV" | Streamlit, README, demo video, public repo | Mốc **CV-ready** |
| **7** | Evaluation + Dockerize | Benchmark 25-30 mẫu, ablation, đóng gói toàn hệ thống | Bảng kết quả, error analysis, `docker-compose.yml` hoàn chỉnh |
| **8** | Hoàn thiện báo cáo + slide | Chương 4-5, chỉnh định dạng, slide, tổng duyệt | Báo cáo .docx/PDF, slide 15-20 trang |

**Mốc quan trọng cho kế hoạch xin intern:** nếu bắt đầu ngay tuần này, hết tuần 4-5 sẽ vào khoảng giữa tháng 11. Từ lúc có end-to-end chạy được (tuần 4-5) bạn đã có thể bắt đầu nộp hồ sơ, ghi trong CV là "MVP hoàn thành, đang đánh giá". Hết tuần 6 là repo + README + demo video hoàn chỉnh.

---

## 2. Chi tiết Từng Tuần

### Tuần 1: Nền tảng, Cơ sở dữ liệu và Bộ dữ liệu mẫu
* **Mục tiêu:** Có hạ tầng chạy được và có dữ liệu thật để thử ngay từ tuần sau.
* **Nhiệm vụ:**
  1. Khởi tạo repo Git (`.gitignore`, `README.md`, cấu trúc thư mục, `.env.example`).
  2. **Kiểm tra phần cứng trước tiên:** chạy thử `frob/qwen3.5-instruct:4b` qua Ollama, đo tốc độ sinh token và RAM/VRAM.
  3. `docker-compose.yml` chạy PostgreSQL; Ollama chạy trên máy chính.
  4. Thiết kế schema PostgreSQL:
     * `contracts`: thông tin file (`id`, `file_name`, `file_path`, `status`, `created_at`).
     * `contract_entities`: kết quả trích xuất dạng JSONB, kèm `verification_status` từng field.
     * `master_entities`: dữ liệu chuẩn để đối soát (mã số thuế, tên công ty, đại diện pháp luật, hạn mức giá trị).
     * `audit_logs`: các sai lệch phát hiện được.
     * Thêm cột `trace_log JSONB` vào `contracts` để lưu vết từng bước agent.
  5. Seed 8-10 công ty vào `master_entities`.
  6. **Tạo bộ hợp đồng mẫu đầu tiên (12-15 file):** tìm mẫu hợp đồng kinh tế/dịch vụ tiếng Việt, sửa thành dữ liệu giả, xuất PDF/DOCX. Cho mỗi file một file đáp án JSON (ground truth). Cần đủ các nhóm:
     * khớp hoàn toàn với `master_entities`,
     * sai mã số thuế / sai tên đại diện,
     * giá trị vượt hạn mức,
     * công ty không có trong hệ thống,
     * thiếu một field quan trọng (để test trường hợp LLM phải trả `null`).
* **Báo cáo:** bắt đầu viết Chương 1 (Giới thiệu & Đặt vấn đề) và nháp phần phân tích yêu cầu.

---

### Tuần 2: Parse tài liệu, Extraction và bản end-to-end mỏng
* **Mục tiêu:** Chạy được từ file hợp đồng ra JSON trích xuất trên bộ mẫu, dù chưa có agent hay API.
* **Nhiệm vụ:**
  1. `DocumentParser`:
     * PDF: `pdfplumber`, lưu `page_number` và `chunk_id` cho từng đoạn.
     * DOCX: `python-docx`, lưu chỉ số đoạn (DOCX không có số trang cố định).
     * Phạm vi: chỉ xử lý PDF có text layer. PDF scan/ảnh nằm ngoài phạm vi, ghi vào mục Hạn chế của báo cáo.
  2. Pydantic schema: Bên A, Bên B, mã số thuế, giá trị hợp đồng, ngày hiệu lực, điều khoản thanh toán. Mỗi field có dạng `{value, quote}`, cho phép `null` khi tài liệu không có thông tin.
  3. Prompt cho `frob/qwen3.5-instruct:4b` (structured output / JSON mode). Dặn rõ: không có thông tin thì trả `null`, `quote` phải chép nguyên văn.
  4. Script CLI: chạy parser + extraction trên toàn bộ bộ mẫu, so với ground truth, in ra **độ chính xác baseline** (chưa có verifier). Con số này dùng làm mốc so sánh ở tuần 7.
  5. pytest cho parser (PDF và DOCX).
* **Báo cáo:** viết Chương 3 phần thiết kế dữ liệu và luồng trích xuất.

---

### Tuần 3: Cơ chế Giảm thiểu Ảo giác (Anti-Hallucination)
* **Mục tiêu:** Mọi giá trị LLM trả ra phải kiểm chứng được bằng văn bản gốc, bằng code thuần (không dùng LLM để kiểm tra LLM).
* **Nhiệm vụ:** thiết kế `CitationVerifier` gồm các bước:
  1. **Chuẩn hóa** cả `quote` và văn bản gốc: Unicode NFC, về chữ thường, gộp khoảng trắng và xuống dòng, bỏ lỗi ngắt từ do PDF.
  2. **Kiểm tra quote tồn tại:** dùng `rapidfuzz` (ưu tiên `partial_ratio` vì quote là đoạn con của văn bản), ngưỡng khởi điểm 85%, chỉnh lại theo dữ liệu thật. Với văn bản dài, so theo chunk để tránh chậm.
  3. **Kiểm tra value-in-quote:** chuẩn hóa giá trị rồi đối chiếu với nội dung quote:
     * số tiền: bỏ dấu chấm/phẩy, "đồng", "VNĐ", xử lý "triệu/tỷ" nếu cần;
     * ngày: đưa về cùng định dạng (nhận cả "ngày 01 tháng 02 năm 2026" và "01/02/2026");
     * mã số thuế: chỉ giữ chữ số.
  4. **Tính vị trí bằng code:** từ vị trí khớp của quote trong văn bản, suy ra `page`/`chunk_id`. Không dùng số trang do LLM tự khai.
  5. Gắn trạng thái cho từng field: `VERIFIED` / `QUOTE_NOT_FOUND` / `VALUE_NOT_IN_QUOTE`.
  6. Unit test: quote thật + giá trị đúng, quote bịa, quote thật nhưng giá trị sai, field `null`.
* **Báo cáo:** viết Chương 2 (cơ sở lý thuyết: LLM, hallucination, LangGraph) và phần mô tả thuật toán verifier.

---

### Tuần 4: Agent Workflow với LangGraph
* **Mục tiêu:** Gói toàn bộ pipeline thành state machine, chạy end-to-end bằng graph.
* **Nhiệm vụ:**
  1. `ContractAuditState` gồm: văn bản gốc, kết quả trích xuất, kết quả verify, kết quả đối soát, báo cáo, số lần retry, `trace_log`.
  2. Các node: `parse_node`, `extract_node`, `verify_citation_node`, `reconcile_db_node` (khung rỗng, hoàn thiện tuần 5), `generate_report_node`, `retry_extraction_node`.
  3. Conditional edges:
     * có field `QUOTE_NOT_FOUND` / `VALUE_NOT_IN_QUOTE` và còn lượt retry → `retry_extraction_node` (prompt siết chặt hơn, chỉ yêu cầu lại các field lỗi);
     * hết lượt retry (**tối đa 2 lần**, tránh vòng lặp vô hạn) → gắn `NEEDS_HUMAN_REVIEW` cho field đó rồi đi tiếp;
     * hợp lệ → `reconcile_db_node`.
  4. Ghi `trace_log` ở mỗi node: tên node, thời điểm, tóm tắt input/output, quyết định rẽ nhánh.
  5. Test graph với các tình huống: trích xuất sạch, có field bị bịa rồi retry thành công, retry thất bại.
* **Báo cáo:** viết Chương 3 phần kiến trúc agent, vẽ StateGraph diagram.

---

### Tuần 5: Đối soát Cơ sở dữ liệu + API
* **Mục tiêu:** Hoàn thiện nghiệp vụ đối soát và mở API.
* **Nhiệm vụ:**
  1. `ReconciliationEngine`:
     * Mã số thuế: chuẩn hóa về chữ số rồi so khớp chính xác.
     * Tên công ty: chuẩn hóa trước (bảng quy đổi "TNHH" ↔ "Trách nhiệm hữu hạn", "CP" ↔ "Cổ phần", bỏ khoảng trắng thừa), sau đó mới so mờ (`token_set_ratio`).
     * Giá trị hợp đồng so với hạn mức trong `master_entities`.
  2. Phân loại bất thường và ghi `audit_logs`:
     * Lỗi 1: thông tin không tồn tại trong hệ thống.
     * Lỗi 2: sai lệch mã số thuế / đại diện pháp luật.
     * Lỗi 3: giá trị vượt ngưỡng.
     * Field `NEEDS_HUMAN_REVIEW` không đưa vào đối soát tự động, báo riêng.
  3. FastAPI (async, `BackgroundTasks`):
     * `POST /api/v1/contracts/upload`
     * `POST /api/v1/audit/process/{contract_id}`
     * `GET /api/v1/audit/result/{contract_id}` (kèm quote, trạng thái verify, cảnh báo, trace log)
  4. Xử lý lỗi cơ bản (file sai định dạng, Ollama không phản hồi, timeout).
  5. pytest cho reconciliation và các endpoint chính.
* **Báo cáo:** viết Chương 3 phần đối soát và API.

---

### Tuần 6: UI tối thiểu + gói đưa vào CV
* **Mục tiêu:** Có sản phẩm người ngoài xem và chạy thử được.
* **Nhiệm vụ:**
  1. Streamlit (bản tối thiểu):
     * Màn 1: upload hợp đồng, gọi API, hiển thị trạng thái xử lý.
     * Màn 2: kết quả thẩm định, tô đỏ field sai lệch/cần review, bấm vào field để xem quote nguồn.
  2. README: mô tả bài toán, sơ đồ kiến trúc, hướng dẫn chạy, mục **Design Decisions** (vì sao LangGraph, vì sao verify bằng quote + value-in-quote thay vì tin vào confidence của LLM), mục **Known Limitations** (PDF scan, một loại hợp đồng, chưa xử lý hàng loạt).
  3. Quay demo video 2-3 phút, đẩy repo lên GitHub public.
* **Mốc CV-ready:** từ đây có thể đưa project vào CV và LinkedIn.

---

### Tuần 7: Đánh giá (Evaluation) và Dockerize
* **Mục tiêu:** Có số liệu thực nghiệm đáng tin để đưa vào báo cáo và để trả lời phỏng vấn.
* **Nhiệm vụ:**
  1. Mở rộng bộ dữ liệu lên **25-30 hợp đồng** (thêm các ca khó: thông tin mâu thuẫn trong cùng tài liệu, định dạng ngày/số tiền khác thường). Với phần "ảo giác", ngoài ca tự nhiên còn **chủ động tiêm lỗi** (sửa quote hoặc giá trị) để có đáp án rõ ràng.
  2. **Ablation** so sánh 3 cấu hình:
     * (a) chỉ extraction, không verifier,
     * (b) extraction + verifier,
     * (c) extraction + verifier + retry.
  3. Các chỉ số: độ chính xác trích xuất theo từng field, precision/recall của phát hiện ảo giác, tỷ lệ phát hiện sai lệch khi đối soát, thời gian xử lý trung bình mỗi hợp đồng. **Không đặt chỉ tiêu cứng từ trước**, báo cáo số đo thật kèm phân tích lỗi (vì sao sai, sai ở loại field nào).
  4. Hoàn thiện `docker-compose.yml` (API + Postgres + Streamlit), thử `docker compose up` trên môi trường sạch. Ollama chạy trên máy chính; API container gọi qua `http://host.docker.internal:11434/v1`.
* **Báo cáo:** viết Chương 4 (triển khai và kết quả thực nghiệm).

---

### Tuần 8: Hoàn thiện báo cáo và Slide
* **Mục tiêu:** Chốt bản bàn giao cho thầy.
* **Nhiệm vụ:**
  1. Viết Chương 5 (Kết luận & Hướng phát triển), rà soát toàn bộ báo cáo theo chuẩn định dạng của trường, đủ sơ đồ (Architecture, StateGraph, Sequence).
  2. Slide 15-20 trang: bài toán, kiến trúc, cơ chế anti-hallucination, demo, bảng ablation, hạn chế.
  3. Tập thuyết trình và chuẩn bị câu hỏi phản biện.
  4. Chỉnh UI/README nếu còn thời gian.

---

## 3. Rủi ro và phương án dự phòng

| Rủi ro | Phương án |
|---|---|
| `frob/qwen3.5-instruct:4b` chạy chậm hoặc trích xuất tiếng Việt chưa tốt | Đo tốc độ và đánh giá chất lượng thực tế ở tuần 1; ghi nhận kết quả trong báo cáo |
| LLM trả JSON sai cấu trúc | Pydantic validate, thất bại thì retry (nằm trong giới hạn 2 lần) |
| Trễ tiến độ | Cắt UI về mức tối thiểu hoặc demo bằng Swagger; không cắt verifier, đối soát và evaluation vì đó là phần cốt lõi |
| Chất lượng hợp đồng mẫu thấp, mẫu quá giống nhau | Thêm đa dạng mẫu ở tuần 7 (khác bố cục, khác cách viết số tiền/ngày) |

## 4. Ngoài phạm vi (ghi vào báo cáo mục Hạn chế)
PDF scan/ảnh cần OCR, xử lý hàng loạt nhiều file đồng thời, multi-agent, fine-tune model, phân quyền người dùng.

---

## 5. Checklist Bàn giao

- [ ] `docker compose up` khởi chạy API, Postgres, Streamlit; Ollama chạy trên máy chính và được API gọi qua `host.docker.internal:11434`.
- [ ] Agent LangGraph chạy đủ: Parse → Extract → Verify (→ Retry) → Reconcile → Report.
- [ ] Verifier phát hiện được cả hai loại lỗi: quote không có trong văn bản gốc, và quote thật nhưng giá trị sai.
- [ ] API trả JSON đầy đủ: giá trị, quote, vị trí, trạng thái verify, cảnh báo sai lệch.
- [ ] Trace log xem lại được từng bước của agent.
- [ ] pytest pass cho parser, verifier, reconciliation, graph.
- [ ] Bảng ablation (a)/(b)/(c) và phân tích lỗi trong báo cáo.
- [ ] UI Streamlit hiển thị rõ kết quả, field sai lệch tô đỏ, xem được quote nguồn.
- [ ] README đầy đủ (Design Decisions, Known Limitations), demo video 2-3 phút.
- [ ] Báo cáo 5 chương đủ sơ đồ, slide 15-20 trang.
- [ ] Tự giải thích được toàn bộ luồng và từng quyết định thiết kế trong dưới 3 phút.

