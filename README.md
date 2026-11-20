# Contract & Document Verification Agent System

Hệ thống tự động đọc hợp đồng định dạng PDF hoặc DOCX, trích xuất các thông tin quan trọng kèm đoạn trích dẫn nguyên văn và tự động đối chiếu thông tin đối tác với cơ sở dữ liệu nội bộ. Điểm cốt lõi của dự án là dùng mã kiểm chứng thuần túy (không dùng LLM để tự chấm LLM) nhằm phát hiện trích xuất sai lệch hoặc suy diễn không có căn cứ trong tài liệu gốc, đồng thời chuyển các trường hợp chưa chắc chắn cho con người kiểm tra.

<!-- Chỗ chèn ảnh chụp màn hình giao diện tổng quan:
![Giao diện chính của Contract Verification Agent](docs/screenshots/01-overview.png)
-->

---

## Kiến trúc hệ thống

### 1. Sơ đồ tổng thể các thành phần

```mermaid
flowchart LR
    U["Người dùng"] --> UI["Streamlit UI<br/>(ui/streamlit_app.py)"]
    UI -->|HTTP API| API["FastAPI Backend<br/>(/api/v1)"]
    API -->|BackgroundTasks| AGENT["LangGraph Agent<br/>(Parse → Verify → Reconcile)"]
    AGENT <-->|OpenAI-compatible API| LLM["Ollama Local LLM<br/>(frob/qwen3.5-instruct:4b)"]
    API <--> DB[("PostgreSQL 16<br/>contracts, master_entities, audit_logs")]
    API <--> VOL[("Volume uploads<br/>PDF / DOCX")]
```

### 2. Sơ đồ LangGraph StateGraph

Sơ đồ dưới đây khớp trực tiếp với cấu trúc biên dịch trong [`app/agent/graph.py`](app/agent/graph.py):

```mermaid
flowchart TD
    START([START]) --> parse_node["parse_node<br/>(Đọc PDF/DOCX thành chunks)"]
    parse_node --> extract_node["extract_node<br/>(LLM trích xuất 7 trường + quote)"]
    extract_node --> verify_citation_node["verify_citation_node<br/>(Kiểm chứng quote & value-in-quote)"]

    verify_citation_node -->|"retry: còn field lỗi<br/>& ENABLE_RETRY=true<br/>& retry_count < MAX_RETRIES"| retry_extraction_node["retry_extraction_node<br/>(Chỉ hỏi lại field lỗi, tăng retry_count)"]
    retry_extraction_node --> verify_citation_node

    verify_citation_node -->|"reconcile: không còn lỗi,<br/>ENABLE_VERIFIER=false,<br/>ENABLE_RETRY=false,<br/>hoặc retry_count >= MAX_RETRIES"| reconcile_db_node["reconcile_db_node<br/>(Gom NEEDS_HUMAN_REVIEW & đối soát PostgreSQL)"]

    reconcile_db_node --> generate_report_node["generate_report_node<br/>(Tổng hợp report & overall_result)"]
    generate_report_node --> END([END])
```

---

## Yêu cầu cài đặt & Môi trường thử nghiệm

- **Docker Desktop** (hỗ trợ Docker Compose v2).
- **Ollama** cài trực tiếp trên máy chủ và đã pull model:
  ```bash
  ollama pull frob/qwen3.5-instruct:4b
  ```
- **Model và phần cứng phát triển thực tế:**
  - Model LLM: `frob/qwen3.5-instruct:4b` (qua endpoint OpenAI-compatible của Ollama).
  - Phần cứng tham chiếu: CPU Intel Core i5-11400H, 24 GB RAM, GPU NVIDIA RTX 3050 Laptop 4 GB VRAM.

---

## Chạy nhanh bằng Docker Compose

1. **Clone repository và tạo file cấu hình `.env`:**
   ```bash
   git clone https://github.com/anh1650000/codoveragsy-project.git
   cd codoveragsy-project
   cp .env.example .env
   ```
   *(Trên Windows PowerShell dùng `Copy-Item .env.example .env`)*

2. **Đảm bảo Ollama đang chạy trên máy chủ và đã có model:**
   ```bash
   ollama list
   ```

3. **Khởi động toàn bộ hệ thống (PostgreSQL + khởi tạo/seed DB + API + UI):**
   ```bash
   docker compose up --build
   ```
   - Giao diện Streamlit UI: `http://localhost:8501`
   - Tài liệu API (Swagger): `http://localhost:8000/docs`
   - Health check API: `http://localhost:8000/api/v1/healthz`

   *(Tùy chọn chạy Ollama trong Docker bằng compose profile:)*
   ```bash
   # Đổi DOCKER_LLM_BASE_URL=http://ollama:11434/v1 trong .env trước khi chạy
   docker compose --profile ollama up --build
   # Lần đầu cần pull model vào container ollama:
   docker compose exec ollama ollama pull frob/qwen3.5-instruct:4b
   ```

---

## Cách dùng thử

### Cách 1: Qua giao diện Streamlit UI
1. Mở `http://localhost:8501`.
2. Chọn một tệp hợp đồng mẫu trong `data/contracts/` (ví dụ `hd_001.pdf`, `hd_003.pdf` hoặc `hd_011.pdf`).
3. Nhấn **Tải lên & Thẩm định** và chờ hệ thống polling trạng thái hoàn tất.
4. Xem kết luận tổng thể (`CLEAN`, `NEEDS_REVIEW`, `DISCREPANCY_FOUND`), bảng 7 trường kèm trạng thái, danh sách `audit_items`, phần mở rộng xem trích dẫn nguồn (`quote`, trang/đoạn, điểm khớp) và `trace_log`.

<!-- Chỗ chèn ảnh chụp màn hình kết quả mẫu:
![Kết quả thẩm định CLEAN](docs/screenshots/02-result-clean.png)
![Kết quả phát hiện sai lệch và quote](docs/screenshots/03-result-discrepancy.png)
-->

### Cách 2: Qua Swagger UI hoặc `curl`
- Mở `http://localhost:8000/docs` để thử trực tiếp 3 endpoint `/api/v1/contracts/upload`, `/api/v1/audit/process/{contract_id}`, `/api/v1/audit/result/{contract_id}`, hoặc dùng `curl`:

```bash
# 1. Tải hợp đồng lên
curl -X POST http://localhost:8000/api/v1/contracts/upload \
  -F "file=@data/contracts/hd_001.pdf"

# 2. Kích hoạt xử lý nền (thay {contract_id} bằng id vừa nhận)
curl -X POST http://localhost:8000/api/v1/audit/process/1

# 3. Tra cứu kết quả kèm trace_log
curl "http://localhost:8000/api/v1/audit/result/1?include_trace=true"
```

---

## Cấu hình `.env`

Các biến chính trong [`.env.example`](.env.example):

| Biến | Mặc định ví dụ | Ý nghĩa |
|---|---|---|
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `contracts` | Thông tin database cho container PostgreSQL |
| `DATABASE_URL` | `postgresql+asyncpg://contracts:contracts@localhost:5432/contracts` | Chuỗi kết nối DB cho script chạy trực tiếp trên máy chủ |
| `DOCKER_DATABASE_URL` | `postgresql+asyncpg://contracts:contracts@postgres:5432/contracts` | Chuỗi kết nối DB dùng bên trong container `api` và `db-init` |
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Endpoint Ollama cho script chạy trực tiếp trên máy chủ |
| `DOCKER_LLM_BASE_URL` | `http://host.docker.internal:11434/v1` | Endpoint Ollama dùng bên trong container `api` (đổi sang `http://ollama:11434/v1` khi dùng `--profile ollama`) |
| `LLM_MODEL` | `frob/qwen3.5-instruct:4b` | Tên model Ollama dùng để trích xuất |
| `LLM_API_KEY` | `ollama` | API key cho client tương thích OpenAI |
| `API_BASE_URL` | `http://localhost:8000` | Địa chỉ API cho UI hoặc `smoke_test.py` khi chạy trên máy chủ |
| `DOCKER_API_BASE_URL` | `http://api:8000` | Địa chỉ API dùng bên trong container `ui` |
| `CITATION_THRESHOLD` | `85` | Ngưỡng điểm khớp mờ tối thiểu cho trích dẫn (`0–100`) |
| `NAME_MATCH_THRESHOLD` | `90` | Ngưỡng điểm khớp mờ tên công ty / người đại diện khi đối soát |
| `NAME_SCORE_MARGIN` | `5.0` | Biên chênh lệch điểm tối thiểu để tránh gán nhầm tên công ty mơ hồ |
| `MAX_RETRIES` | `2` | Số lần tối đa yêu cầu LLM trích xuất lại các trường lỗi |
| `ENABLE_VERIFIER` | `true` | Bật/tắt `CitationVerifier` (phục vụ kiểm thử ablation) |
| `ENABLE_RETRY` | `true` | Bật/tắt nhánh retry các trường lỗi trích dẫn |
| `UPLOAD_DIR` / `DOCKER_UPLOAD_DIR` | `./data/uploads` / `/app/data/uploads` | Thư mục lưu tệp tải lên |
| `MAX_UPLOAD_MB` | `10` | Giới hạn dung lượng tệp tải lên (MB) |
| `UI_POLL_INTERVAL_SECONDS` | `2` | Chu kỳ polling kết quả (giây) |
| `UI_POLL_TIMEOUT_SECONDS` | `600` | Thời gian chờ tối đa trên UI (giây) |
| `SMOKE_TEST_TIMEOUT_SECONDS` | `600` | Thời gian chờ tối đa của `scripts/smoke_test.py` (giây) |

---

## Cấu trúc thư mục

```text
├── app/
│   ├── main.py              # Khởi tạo ứng dụng FastAPI
│   ├── core/config.py       # Đọc cấu hình từ biến môi trường / .env
│   ├── api/                 # Routes /api/v1 và dependency injection
│   ├── db/                  # SQLAlchemy models, repository, session, seed dữ liệu
│   ├── parsing/             # Đọc PDF (pdfplumber) và DOCX (python-docx)
│   ├── llm/                 # OpenAI-compatible client và prompt trích xuất/retry
│   ├── extraction/          # Pydantic schema và extractor có retry lỗi JSON
│   ├── guardrails/          # Normalizers tiếng Việt/quốc tế và CitationVerifier
│   ├── reconciliation/      # Rule-based ReconciliationEngine cho Bên B
│   └── agent/               # LangGraph state, nodes và StateGraph
├── ui/
│   ├── streamlit_app.py     # Giao diện Streamlit tối thiểu (thin HTTP client)
│   ├── api_client.py        # Wrapper gọi API qua httpx
│   └── formatters.py        # Hàm thuần định dạng nhãn, màu trạng thái, vị trí
├── scripts/
│   ├── generate_dataset.py  # Sinh hợp đồng mẫu và ground truth JSON
│   ├── smoke_test.py        # Kiểm tra nhanh stack đang chạy qua HTTP
│   ├── run_graph.py         # Chạy graph trực tiếp qua CLI
│   ├── run_eval.py          # Đánh giá extraction, verifier và đối soát
│   └── check_llm_speed.py   # Đo tốc độ sinh token của model
├── data/
│   ├── contracts/           # Hợp đồng mẫu (dữ liệu giả)
│   └── ground_truth/        # Đáp án JSON tương ứng từng hợp đồng mẫu
├── tests/                   # Bộ unit test và integration test bằng pytest
├── Dockerfile               # Multi-stage Dockerfile cho api và ui
├── docker-compose.yml       # PostgreSQL, db-init, api, ui (+ profile ollama)
├── requirements.txt         # Thư viện cho API/backend
├── requirements-ui.txt      # Thư viện gọn nhẹ cho Streamlit UI
└── .env.example             # Mẫu cấu hình môi trường
```

---

## Kiểm thử (Testing)

### Chạy bộ unit & integration test (không cần Ollama hay PostgreSQL chạy ngoài)
```bash
pip install -r requirements.txt -r requirements-ui.txt
pytest -q
```

### Chạy smoke test qua HTTP trên stack Docker đang chạy
```bash
python scripts/smoke_test.py --file data/contracts/hd_001.pdf
```

---

## Dữ liệu mẫu

Toàn bộ tên công ty, mã số thuế, người đại diện và nội dung hợp đồng trong `app/db/seed_data.py`, `data/contracts/` và `data/ground_truth/` **hoàn toàn là dữ liệu giả**, được sinh tự động bằng [`scripts/generate_dataset.py`](scripts/generate_dataset.py) để phục vụ kiểm thử và đối chiếu tự động, không chứa thông tin thật của bất kỳ cá nhân hay tổ chức nào.

---

## Design Decisions

### 1. Vì sao chọn LangGraph?

Hàm tuần tự hoàn toàn khả thi cho bài toán này. Tuy nhiên, nếu viết bằng hàm tuần tự, mình phải tự quản lý số lần retry, đảm bảo khi retry chỉ gọi lại các trường lỗi, ghi trace log rõ ràng, và có cơ chế khôi phục trạng thái khi lỗi xảy ra ở bước retry hoặc lỗi file. `StateGraph` không phức tạp hơn đáng kể, nhưng quản lý state tập trung và tường minh, nên dễ kiểm soát hơn khi số bước và số nhánh tăng lên. Vì vậy, chọn `StateGraph` cho bài toán nhỏ này là một sự đánh đổi giữa độ phức tạp hiện tại và khả năng mở rộng sau này, chứ không phải lựa chọn tối ưu nhất.

### 2. Vì sao kiểm chứng bằng code thuần?

Dùng confidence hoặc LLM thứ hai để kiểm tra đều không đáng tin, vì cả hai đều do chính LLM sinh ra. Confidence dựa trên xác suất sinh token nên không ổn định, thay đổi giữa các lần chạy, và LLM vẫn có thể bịa kết quả với mức tự tin cao. Nếu dùng LLM thứ hai, hệ thống có nguy cơ đồng thuận sai: khi cả hai mô hình cùng ảo giác và cho cùng một kết quả sai, phép so sánh đồng thuận vẫn trả về "đúng". Về mặt logic, A ↔ B cho kết quả 1 khi hai vế cùng giá trị, nên 0 ↔ 0 cho kết quả 1. Vì vậy, kiểm chứng bằng `quote` và `value-in-quote` dựa trên văn bản gốc, không phụ thuộc vào việc các mô hình có đồng ý với nhau hay không.

### 3. Vì sao giới hạn số lần retry?

Mỗi lần retry là một lượt gọi LLM chạy local nên tốn thời gian đáng kể. Nếu không giới hạn, khi LLM không tìm được giá trị đúng, pipeline có thể lặp mãi và không bao giờ kết thúc. Với các field vẫn lỗi sau khi hết số lần thử, tiếp tục thử thường chỉ lặp lại cùng kết quả, nên đánh dấu `NEEDS_HUMAN_REVIEW` để con người kiểm tra là cách an toàn hơn.

Số 2 là giá trị khởi đầu. Mình chọn nó để cân bằng giữa thời gian chạy trên máy cá nhân và khả năng sửa được lỗi. Con số này chưa được kiểm chứng, nó sẽ được so sánh với các cấu hình khác để xác định giá trị phù hợp.

---

## Known Limitations

- Chỉ hỗ trợ tệp PDF có lớp văn bản (text layer) và DOCX; PDF dạng ảnh quét (scan/OCR) nằm ngoài phạm vi.
- Chỉ áp dụng cho ngữ cảnh hợp đồng và cố định 7 trường thông tin trích xuất.
- Chưa hỗ trợ xử lý hàng loạt nhiều hợp đồng đồng thời trong một lượt.
- `CitationVerifier` chỉ chứng minh được *giá trị xuất hiện trong đoạn trích dẫn đã khớp*, chưa chứng minh được đoạn văn đó có đúng ngữ nghĩa gán cho trường đang xét hay không (đã ghi nhận ca kiểm thử minh họa trong `tests/test_citation_verifier.py`).
- Chạy model kích thước nhỏ (`frob/qwen3.5-instruct:4b`) cục bộ trên laptop 4 GB VRAM nên thời gian xử lý mỗi hợp đồng chậm (có thể mất vài phút tùy độ dài và số lần retry).
- Bộ dữ liệu mẫu hiện tại là dữ liệu tự sinh ở quy mô nhỏ (12 tệp gắn ground truth trong tập phát triển).

---

## Kết quả đánh giá

Cập nhật sau khi có số liệu thực nghiệm.

---

## Giấy phép

Phát hành theo giấy phép [MIT License](LICENSE).
