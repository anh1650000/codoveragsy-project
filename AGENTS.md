# AGENTS — Contract & Document Verification Agent System

> Đặt file này ở thư mục gốc của repo với tên `AGENTS.md` (Codex tự đọc file tên này trước khi làm việc).
> Đây là **nguồn sự thật duy nhất** về thiết kế. `docs/ROADMAP.md` cho biết làm gì theo tuần. Nếu hai file mâu thuẫn, **dừng lại và hỏi**, không tự chọn.

---

## 0. Dành cho AI agent: đọc trước khi làm bất cứ việc gì

Bạn đang giúp một sinh viên năm 4 Khoa học Máy tính (Đại học Cần Thơ) xây niên luận ngành. Sản phẩm này cũng là project để xin thực tập AI/GenAI tại TP.HCM, nên sinh viên **phải hiểu và giải thích được từng dòng quan trọng** khi phỏng vấn. Ưu tiên code đơn giản, rõ ràng, có test hơn là code ngắn hoặc "thông minh".

Mỗi phiên làm việc:

1. Đọc file này và `docs/ROADMAP.md`.
2. Xác định tuần đang làm (người dùng sẽ nói). Chỉ làm đúng phạm vi tuần đó.
3. Tóm tắt kế hoạch ngắn: file sẽ tạo/sửa, cách kiểm chứng. Có điểm chưa rõ thì hỏi trước, không thì làm.
4. Làm xong thì chạy test, rồi báo cáo theo mục 13.

---

## 1. Dự án

**Bài toán:** Công ty nhận hợp đồng/hồ sơ (PDF/DOCX). Hệ thống tự động: đọc tài liệu → trích xuất thông tin có cấu trúc kèm trích dẫn nguồn → kiểm chứng trích dẫn bằng code → đối soát với PostgreSQL → xuất báo cáo kèm cảnh báo.

**Điểm cốt lõi (không được làm yếu đi):** kiểm soát ảo giác (hallucination) bằng xác thực trích dẫn. Mọi giá trị LLM trả ra phải chứng minh được bằng đoạn văn nguyên văn trong tài liệu gốc, và việc kiểm chứng do **code thuần** thực hiện, không dùng LLM để kiểm tra LLM.

**Quy ước nghiệp vụ đã chốt:** Bên A là công ty "của mình", Bên B là **đối tác** cần thẩm định. Đối soát chỉ áp dụng cho Bên B với bảng `master_entities`.

---

## 2. Luật làm việc (bắt buộc)

1. **Đúng phạm vi tuần.** Không làm trước, không thêm tính năng, không refactor thứ không liên quan. Thấy cải tiến hay thì ghi vào cuối báo cáo như đề xuất.
2. **Không tự đổi quyết định ở mục 14.** Muốn đổi thì hỏi.
3. **Hỏi khi có nhiều cách hợp lý** (chọn thư viện, cách tổ chức module...). Nêu 2-3 lựa chọn với ưu nhược ngắn gọn, để sinh viên chọn.
4. **Không thêm thư viện** ngoài mục 3 khi chưa hỏi.
5. **Viết test cùng lúc với code**, không để dồn. Test pass mới được báo "xong".
6. **Code guardrail/verifier/reconciliation phải tường minh:** hàm nhỏ, tên rõ, **comment tiếng Việt giải thích vì sao** (không chỉ giải thích làm gì). Sinh viên sẽ đọc lại những phần này nhiều lần.
7. **Không hardcode secret hay đường dẫn máy cá nhân.** Dùng `.env`, kèm `.env.example`.
8. **Không nuốt lỗi** (`except: pass`). Lỗi phải được log hoặc trả về đúng trạng thái.
9. **Không bịa kết quả.** Nếu không chạy được test/lệnh, nói rõ là chưa chạy, đừng báo "đã pass".
10. **Commit nhỏ, thông điệp rõ** theo dạng `feat:`, `fix:`, `test:`, `docs:`, `chore:`. Mỗi commit một việc.
11. Định danh (tên biến, hàm, class) viết tiếng Anh. Comment và docstring viết tiếng Việt, ngắn gọn.
12. Không bao giờ để LLM quyết định kết quả đối soát hoặc kết quả verify. LLM chỉ làm việc trích xuất.

---

## 3. Tech stack và cấu hình

| Thành phần     | Công nghệ                                                                          |
| -------------- | ---------------------------------------------------------------------------------- |
| Ngôn ngữ       | Python 3.11+                                                                       |
| API            | FastAPI (async), `BackgroundTasks` cho tác vụ dài                                  |
| Agent          | LangGraph (`StateGraph`)                                                           |
| LLM            | Model Qwen qua Ollama cài trên máy chính; gọi qua giao diện **tương thích OpenAI** |
| Validation     | Pydantic v2                                                                        |
| DB             | PostgreSQL 16, SQLAlchemy 2.x async + asyncpg, Alembic nếu cần migration           |
| Parse tài liệu | `pdfplumber` (PDF), `python-docx` (DOCX)                                           |
| So khớp mờ     | `rapidfuzz`                                                                        |
| UI             | Streamlit                                                                          |
| Test           | `pytest`, `pytest-asyncio`                                                         |
| Đóng gói       | Docker, Docker Compose                                                             |
| Log            | `structlog` hoặc `logging` chuẩn, cộng với `trace_log` trong state                 |

**Biến môi trường (`.env.example`):**

```
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/contracts
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=frob/qwen3.5-instruct:4b
LLM_API_KEY=ollama
CITATION_THRESHOLD=85
NAME_MATCH_THRESHOLD=90
MAX_RETRIES=2
ENABLE_VERIFIER=true
ENABLE_RETRY=true
UPLOAD_DIR=./data/uploads
```

Mọi lời gọi LLM đi qua **một** module `app/llm/client.py` đọc `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` từ cấu hình. Mặc định Ollama chạy trên máy chính (`localhost:11434`); container cần gọi Ollama trên máy chính qua `host.docker.internal:11434`. `ENABLE_VERIFIER` và `ENABLE_RETRY` dùng cho thí nghiệm ablation ở tuần 7: graph phải chạy đúng khi tắt từng cái.

Về structured output: ưu tiên dùng JSON mode / `response_format` nếu phiên bản Ollama đang dùng hỗ trợ (kiểm tra thực tế, đừng giả định). Dù dùng cách nào, kết quả luôn phải qua `model_validate` của Pydantic, lỗi thì retry theo mục 7.

---

## 4. Cấu trúc thư mục

```
repo/
├── AGENTS.md
├── docs/ROADMAP.md
├── app/
│   ├── main.py
│   ├── core/            # config.py, logging.py
│   ├── api/             # routes.py, deps.py
│   ├── db/              # session.py, models.py, seed.py
│   ├── parsing/         # document_parser.py
│   ├── llm/             # client.py, prompts.py
│   ├── extraction/      # schema.py (Pydantic), extractor.py
│   ├── guardrails/      # normalizers.py, citation_verifier.py
│   ├── reconciliation/  # engine.py
│   └── agent/           # state.py, nodes.py, graph.py
├── ui/streamlit_app.py
├── scripts/             # generate_dataset.py, run_eval.py, check_llm_speed.py
├── data/
│   ├── contracts/       # PDF/DOCX mẫu
│   └── ground_truth/    # JSON đáp án, cùng tên file với hợp đồng
├── tests/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

---

## 5. Database schema (PostgreSQL)

```sql
CREATE TABLE master_entities (
    id SERIAL PRIMARY KEY,
    vat_code VARCHAR(20) UNIQUE NOT NULL,        -- chỉ chữ số, 10 số (mã chính)
    company_name VARCHAR(255) NOT NULL,
    legal_representative VARCHAR(255),
    max_contract_value NUMERIC(18,0),            -- hạn mức, VND
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE contracts (
    id SERIAL PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'UPLOADED',  -- UPLOADED, PROCESSING, DONE, FAILED
    overall_result VARCHAR(30),                      -- CLEAN, NEEDS_REVIEW, DISCREPANCY_FOUND
    error_message TEXT,
    trace_log JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE contract_entities (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    fields JSONB NOT NULL,          -- danh sách VerifiedField (mục 6)
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    error_type VARCHAR(30) NOT NULL,  -- ENTITY_NOT_FOUND, IDENTITY_MISMATCH, VALUE_OVER_LIMIT, NEEDS_HUMAN_REVIEW
    field_name VARCHAR(50),
    extracted_value TEXT,
    expected_value TEXT,
    detail TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

`seed.py` nạp 8-10 công ty vào `master_entities`, dữ liệu **khớp với bộ hợp đồng mẫu** (mục 11).

---

## 6. Data models (Pydantic v2)

```python
class ExtractedField(BaseModel):
    value: str | None      # chép đúng như trong tài liệu, chưa chuẩn hóa; None nếu tài liệu không có
    quote: str | None      # đoạn nguyên văn chứa value; None nếu value là None

class RawExtraction(BaseModel):   # đầu ra của LLM
    party_a_name: ExtractedField
    party_b_name: ExtractedField
    party_b_tax_code: ExtractedField
    party_b_legal_representative: ExtractedField
    contract_value: ExtractedField
    effective_date: ExtractedField
    payment_terms: ExtractedField

class FieldStatus(str, Enum):
    VERIFIED = "VERIFIED"
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    VALUE_NOT_IN_QUOTE = "VALUE_NOT_IN_QUOTE"
    NOT_PRESENT = "NOT_PRESENT"

class VerifiedField(BaseModel):   # đầu ra của CitationVerifier
    name: str
    value: str | None
    quote: str | None
    status: FieldStatus
    match_score: float | None     # điểm khớp quote, 0-100
    page: int | None              # do CODE tính, không lấy từ LLM
    chunk_id: int | None

class AuditItem(BaseModel):
    error_type: Literal["ENTITY_NOT_FOUND", "IDENTITY_MISMATCH", "VALUE_OVER_LIMIT", "NEEDS_HUMAN_REVIEW"]
    field_name: str | None
    extracted_value: str | None
    expected_value: str | None
    detail: str
```

**Trường bắt buộc** (`REQUIRED_FIELDS`): `party_b_name`, `party_b_tax_code`, `contract_value`. Các trường còn lại là tùy chọn.

---

## 7. Agent (LangGraph)

```python
class ContractAuditState(TypedDict):
    contract_id: int
    file_path: str
    chunks: list[dict]               # {chunk_id, page, text}; DOCX thì page = None
    raw_extraction: RawExtraction | None
    verified_fields: list[VerifiedField]
    retry_count: int
    audit_items: list[AuditItem]
    overall_result: str | None
    report: dict | None
    trace_log: list[dict]            # {node, ts, summary, decision}
```

**Các node:** `parse_node` → `extract_node` → `verify_citation_node` → (rẽ nhánh) → `retry_extraction_node` | `reconcile_db_node` → `generate_report_node`.

**Rẽ nhánh sau `verify_citation_node`:**

- Có field `QUOTE_NOT_FOUND` hoặc `VALUE_NOT_IN_QUOTE`, `ENABLE_RETRY=true` và `retry_count < MAX_RETRIES` → `retry_extraction_node`, rồi quay lại `verify_citation_node`.
- Ngược lại → `reconcile_db_node`. Field còn lỗi lúc này sinh `AuditItem(NEEDS_HUMAN_REVIEW)` và **không** đưa vào đối soát tự động.

**`retry_extraction_node`:** chỉ yêu cầu lại các field lỗi, prompt nói rõ field nào sai vì lý do gì ("quote bạn đưa không xuất hiện trong tài liệu", "giá trị không nằm trong quote") và nhắc: không có thông tin thì trả `null`. Tăng `retry_count`. **Tối đa `MAX_RETRIES` lần**, không được có vòng lặp vô hạn.

**Lỗi LLM trả sai cấu trúc JSON:** thử lại tối đa 2 lần trong `extractor` (tính riêng với retry ở trên), quá số lần thì đánh `status=FAILED` cho contract kèm `error_message`.

**`trace_log`:** mỗi node thêm một mục `{node, ts, summary, decision}` (vd `decision="retry: 2 field lỗi"`). Cuối cùng lưu vào `contracts.trace_log`.

**`overall_result`** (ưu tiên từ trên xuống):

1. `DISCREPANCY_FOUND` nếu có `ENTITY_NOT_FOUND`, `IDENTITY_MISMATCH` hoặc `VALUE_OVER_LIMIT`.
2. `NEEDS_REVIEW` nếu có `NEEDS_HUMAN_REVIEW`.
3. `CLEAN` nếu còn lại.

---

## 8. CitationVerifier (đặc tả, `app/guardrails/`)

Đầu vào: `RawExtraction`, `chunks`. Đầu ra: `list[VerifiedField]`.

**Bước 0: chuẩn bị.** Chuẩn hóa từng chunk bằng `normalize_text`: Unicode NFC, chữ thường, thay `\u00a0` bằng khoảng trắng, bỏ ký tự zero-width và soft hyphen, gộp mọi khoảng trắng/xuống dòng thành một dấu cách. Ghép các chunk đã chuẩn hóa thành một chuỗi toàn văn, **giữ bảng offset** (vị trí bắt đầu/kết thúc trong chuỗi chuẩn hóa → `chunk_id`, `page`).

**Với từng field:**

1. `value is None` → `NOT_PRESENT`. Xong.
2. `quote is None` hoặc rỗng → `QUOTE_NOT_FOUND`.
3. **Kiểm tra quote tồn tại:** chuẩn hóa quote rồi dùng `rapidfuzz.fuzz.partial_ratio_alignment` trên chuỗi toàn văn. Điểm `< CITATION_THRESHOLD` → `QUOTE_NOT_FOUND`. Điểm đạt → lấy vị trí khớp, tra bảng offset ra `page` và `chunk_id` (**không** nhận số trang từ LLM).
4. **Kiểm tra value-in-quote:** dùng đoạn văn gốc tại vị trí khớp (không phải quote do LLM gõ) và so với `value` bằng normalizer theo loại field. Không khớp → `VALUE_NOT_IN_QUOTE`. Khớp → `VERIFIED`.

**Normalizers (`normalizers.py`), mỗi cái có unit test:**

- `parse_vnd(text) -> Decimal | None` và hàm trích mọi số tiền ứng viên trong một đoạn: bỏ dấu phân cách nghìn (`.` `,`), bỏ "đồng/VNĐ/VND", xử lý "triệu", "tỷ". Bắt đầu đơn giản, mở rộng khi test yêu cầu.
- `parse_vn_date(text) -> date | None`: nhận `dd/mm/yyyy`, `dd-mm-yyyy`, `ngày D tháng M năm YYYY`. Hàm trích mọi ngày ứng viên trong đoạn.
- `normalize_tax_code(text) -> str`: chỉ giữ chữ số; mã chính là 10 số đầu (bỏ hậu tố chi nhánh `-001`).
- `normalize_company_name(text) -> str`: chữ thường, bảng quy đổi `trách nhiệm hữu hạn → tnhh`, `cổ phần → cp`, `công ty → ct`..., bỏ dấu câu thừa. Bảng quy đổi để ở một hằng số dễ sửa.

Quy tắc so value-in-quote theo field: tiền → số trong value ∈ tập số tìm được trong quote; ngày → ngày của value ∈ tập ngày trong quote; MST → chuỗi số của value nằm trong chuỗi số của quote; tên → value chuẩn hóa nằm trong quote chuẩn hóa; `payment_terms` → so mờ với ngưỡng `CITATION_THRESHOLD`.

---

## 9. ReconciliationEngine (`app/reconciliation/engine.py`)

Chỉ dùng các field `VERIFIED`. Không gọi LLM.

1. Tìm công ty theo `party_b_tax_code` (đã chuẩn hóa) trong `master_entities.vat_code`.
2. **Tìm thấy:**
    - So tên: `rapidfuzz.fuzz.token_set_ratio` giữa tên đã chuẩn hóa. `< NAME_MATCH_THRESHOLD` → `IDENTITY_MISMATCH` (field `party_b_name`).
    - Nếu có `party_b_legal_representative` đã verify: so mờ với `legal_representative` trong DB, không khớp → `IDENTITY_MISMATCH`.
    - Nếu `contract_value > max_contract_value` → `VALUE_OVER_LIMIT`.
3. **Không tìm thấy theo MST:** thử tìm theo tên (so mờ ≥ `NAME_MATCH_THRESHOLD`). Tìm được → `IDENTITY_MISMATCH` (MST trong hợp đồng khác MST trong hệ thống). Không tìm được → `ENTITY_NOT_FOUND`.
4. Nếu `party_b_tax_code` không được verify: chỉ thử theo tên; không tìm được thì `NEEDS_HUMAN_REVIEW` thay vì kết luận vội.
5. Mỗi `AuditItem` ghi vào `audit_logs` kèm giá trị trích xuất và giá trị kỳ vọng.

---

## 10. API (`/api/v1`)

| Method | Path                           | Mô tả                                                                                                                  |
| ------ | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| POST   | `/contracts/upload`            | Nhận file PDF/DOCX (multipart), kiểm tra định dạng và dung lượng, lưu file, tạo bản ghi `contracts`, trả `contract_id` |
| POST   | `/audit/process/{contract_id}` | Chạy graph bằng `BackgroundTasks`, trả ngay `202` và `status=PROCESSING`                                               |
| GET    | `/audit/result/{contract_id}`  | Trả trạng thái và kết quả; có tham số `include_trace=true` để lấy `trace_log`                                          |
| GET    | `/healthz`                     | Health check                                                                                                           |

Mẫu kết quả khi `status=DONE`:

```json
{
    "contract_id": 7,
    "status": "DONE",
    "overall_result": "DISCREPANCY_FOUND",
    "fields": [
        {
            "name": "party_b_tax_code",
            "value": "0312345678",
            "quote": "Mã số thuế: 0312345678",
            "status": "VERIFIED",
            "match_score": 100.0,
            "page": 1,
            "chunk_id": 4
        }
    ],
    "audit_items": [
        {
            "error_type": "VALUE_OVER_LIMIT",
            "field_name": "contract_value",
            "extracted_value": "2000000000",
            "expected_value": "1000000000",
            "detail": "Giá trị hợp đồng vượt hạn mức của đối tác"
        }
    ],
    "retry_count": 1
}
```

Lỗi phải trả đúng mã HTTP và thông điệp rõ: sai định dạng file (415), file quá lớn (413), `contract_id` không tồn tại (404), Ollama không phản hồi (503 / `status=FAILED` kèm `error_message`).

---

## 11. Bộ dữ liệu mẫu và ground truth

Sinh bằng `scripts/generate_dataset.py` để **ground truth luôn chính xác** (cùng dữ liệu sinh ra hợp đồng cũng sinh ra đáp án).

- Dùng **3-4 template hợp đồng** khác nhau (khác bố cục, cách viết số tiền, cách viết ngày) và thay dữ liệu giả vào. Mục đích: tránh dữ liệu quá đồng đều làm điểm đánh giá cao ảo.
- Xuất DOCX bằng `python-docx`. Xuất PDF bằng LibreOffice headless nếu có, hoặc `reportlab` với font Unicode hỗ trợ tiếng Việt. Kiểm tra PDF có text layer (copy được chữ), không phải ảnh.
- Tuần 1: 12-15 file. Tuần 7: mở rộng lên 25-30 file, thêm template mới và các ca khó (thông tin mâu thuẫn trong cùng tài liệu, định dạng lạ).
- Dữ liệu công ty, MST, tên đại diện đều là **giả**. Không dùng thông tin thật của tổ chức hay cá nhân nào.

**Ma trận kịch bản (mỗi loại có ít nhất 2 file ở tuần 1):**

| scenario               | Mô tả                                       | `expected_overall_result` | `expected_audit_error_types` |
| ---------------------- | ------------------------------------------- | ------------------------- | ---------------------------- |
| `CLEAN`                | Khớp hoàn toàn với `master_entities`        | CLEAN                     | []                           |
| `WRONG_TAX_CODE`       | Đúng tên công ty nhưng MST khác DB          | DISCREPANCY_FOUND         | [IDENTITY_MISMATCH]          |
| `WRONG_REPRESENTATIVE` | Đúng MST, sai người đại diện                | DISCREPANCY_FOUND         | [IDENTITY_MISMATCH]          |
| `OVER_LIMIT`           | Giá trị vượt hạn mức                        | DISCREPANCY_FOUND         | [VALUE_OVER_LIMIT]           |
| `UNKNOWN_ENTITY`       | Công ty không có trong hệ thống             | DISCREPANCY_FOUND         | [ENTITY_NOT_FOUND]           |
| `MISSING_FIELD`        | Thiếu một trường bắt buộc (vd không có MST) | NEEDS_REVIEW              | [NEEDS_HUMAN_REVIEW]         |

**Định dạng ground truth** (`data/ground_truth/<tên file>.json`):

```json
{
    "file": "hd_007.docx",
    "template": "T2",
    "scenario": "WRONG_TAX_CODE",
    "fields": {
        "party_a_name": "Công ty TNHH Alpha",
        "party_b_name": "Công ty Cổ phần Beta",
        "party_b_tax_code": "0312345678",
        "party_b_legal_representative": "Nguyễn Văn A",
        "contract_value": 500000000,
        "effective_date": "2026-03-01",
        "payment_terms": null
    },
    "expected_overall_result": "DISCREPANCY_FOUND",
    "expected_audit_error_types": ["IDENTITY_MISMATCH"]
}
```

`fields` lưu giá trị **đã chuẩn hóa** (số nguyên VND, ngày ISO, MST chỉ chữ số) và `null` nếu tài liệu không có trường đó.

**Bối cảnh cấu hình:**

- Ollama chạy native trên máy mình (LLM_BASE_URL=http://localhost:11434/v1), model đang dùng: [frob/qwen3.5-instruct:4b].
- Máy chỉ có 4GB VRAM, nên giữ ngữ cảnh ngắn (khoảng 4096-8192 token).
- Nếu model có chế độ thinking thì cần tắt cho tác vụ trích xuất. Hãy kiểm tra cách tắt nào chạy thật với phiên bản Ollama mình đang cài (qua endpoint tương thích OpenAI hay API gốc của Ollama), báo mình kết quả kiểm tra trước khi chọn cách làm, đừng giả định.
- Toàn bộ file Tuần 1 trong data/contracts là tập DEV: dùng thoải mái để chỉnh prompt. Tập test riêng sẽ làm ở Tuần 7, không chỉnh bất cứ thứ gì theo tập test.

---

## 12. Testing và Evaluation

**Unit/integration test (`tests/`), tối thiểu:**

- Parser: PDF và DOCX, có page/chunk_id đúng.
- Normalizers: nhiều định dạng tiền, ngày, MST, tên công ty.
- CitationVerifier: quote thật + giá trị đúng; quote bịa; quote thật nhưng giá trị sai; field `null`; quote xuyên qua ranh giới hai chunk.
- Graph: trích xuất sạch; field sai rồi retry thành công; retry hết lượt thì thành `NEEDS_HUMAN_REVIEW`. Dùng LLM giả (mock) để kết quả xác định.
- Reconciliation: đủ 4 loại `error_type` và trường hợp khớp.
- API: upload sai định dạng, xử lý và lấy kết quả.

**Evaluation (`scripts/run_eval.py`), tuần 7:**

1. **End-to-end với LLM thật** trên 25-30 file, so với ground truth: độ chính xác trích xuất theo từng field (so sau chuẩn hóa), độ chính xác `overall_result`, tỷ lệ phát hiện đúng `expected_audit_error_types`, thời gian xử lý mỗi hợp đồng.
2. **Stress test verifier có chủ đích:** lấy trích xuất đúng từ ground truth, **tự làm hỏng** (sửa quote / đổi giá trị / bịa quote), chạy qua verifier, đo precision/recall phát hiện. Đây là cách có đáp án rõ ràng để đo "phát hiện ảo giác".
3. **Ablation** qua cờ cấu hình: (a) `ENABLE_VERIFIER=false`, (b) verifier bật + `ENABLE_RETRY=false`, (c) cả hai bật. Xuất bảng so sánh ra CSV/markdown.
4. **Không đặt chỉ tiêu cứng từ trước.** Báo cáo số đo thật và phân tích các ca sai (loại field nào hay sai, vì sao).

---

## 13. Báo cáo sau mỗi tuần (format bắt buộc)

```
## Tuần N hoàn thành
- Đã làm: ...
- File tạo/sửa: ...
- Cách chạy thử: (lệnh cụ thể)
- Test: (đã chạy lệnh nào, kết quả; chưa chạy thì nói rõ)
- Quyết định kỹ thuật đã đưa ra và lý do: ...
- Phần sinh viên cần tự đọc kỹ để giải thích được: (tên file/hàm)
- Rủi ro hoặc việc còn dang dở: ...
- Đề xuất (không làm khi chưa được duyệt): ...
- Cần sinh viên quyết định gì trước khi sang tuần sau: ...
```

---

## 14. Quyết định thiết kế đã chốt (không tự đổi)

1. Kiểm chứng trích dẫn bằng code thuần (`rapidfuzz` + normalizers), không dùng LLM làm bộ kiểm tra.
2. Có **hai** lớp kiểm tra: quote tồn tại trong tài liệu, và giá trị nằm trong quote.
3. Trang/vị trí do code tính từ vị trí khớp, không tin số trang LLM khai.
4. Retry tối đa `MAX_RETRIES` lần, chỉ yêu cầu lại field lỗi. Hết lượt thì chuyển người duyệt (`NEEDS_HUMAN_REVIEW`), không đoán.
5. Field không có trong tài liệu phải trả `null`, hệ thống coi đó là hợp lệ (`NOT_PRESENT`), không phải lỗi.
6. Mọi lời gọi LLM qua một client tương thích OpenAI, cấu hình bằng `.env`.
7. Chỉ xử lý PDF có text layer và DOCX. PDF scan nằm ngoài phạm vi.
8. Đối soát chỉ áp dụng cho Bên B.

---

## 15. Ngoài phạm vi (không làm, kể cả khi "dễ làm thêm")

OCR cho PDF scan, xử lý hàng loạt nhiều file cùng lúc, Celery/Redis, multi-agent, fine-tune model, đăng nhập/phân quyền, nhiều loại tài liệu ngoài hợp đồng, giao diện phức tạp ngoài Streamlit tối thiểu.
