# WEEKLY_PROMPTS — Prompt giao việc cho AI agent theo từng tuần

## Cách dùng

1. Đặt `AGENTS.md` ở gốc repo và `ROADMAP.md` vào `docs/ROADMAP.md`.
2. Mỗi phiên làm việc, copy **một** prompt tuần bên dưới (đừng giao nhiều tuần cùng lúc).
3. Đọc báo cáo của AI, tự trả lời các câu hỏi "Bạn phải tự giải thích được" trước khi sang tuần sau.
4. Trước khi sang tuần mới, commit code và mở phiên mới (hoặc dùng prompt mở phiên ở mục A).

Các prompt đều giả định AI đọc được repo. Nếu dùng chat thường (không đọc được file), dán nội dung `AGENTS.md` vào đầu cuộc trò chuyện.

---

## A. Prompt mở phiên (dùng khi quay lại làm tiếp)

```
Đọc AGENTS.md và docs/ROADMAP.md trong repo này.
Sau đó cho mình biết: (1) trạng thái hiện tại của repo (đã có những gì, dựa trên code thật, không đoán),
(2) theo roadmap thì phần nào đang dang dở.
Chưa viết code. Mình sẽ giao việc của tuần tiếp theo sau.
```

---

## B. Prompt từng tuần

### Tuần 1: Nền tảng, DB và bộ dữ liệu mẫu

```
Đọc AGENTS.md và docs/ROADMAP.md. Hôm nay làm TUẦN 1.

Việc cần làm:
1. Khởi tạo cấu trúc thư mục theo mục 4 của AGENTS.md, requirements.txt, .gitignore, .env.example.
2. Viết scripts/check_llm_speed.py: gọi model qua client tương thích OpenAI (đọc LLM_BASE_URL, LLM_MODEL từ .env), đo thời gian và số token/giây với một prompt trích xuất mẫu. Hướng dẫn mình chạy và đọc kết quả. Máy mình chạy được model nào thì mình báo lại.
3. docker-compose.yml với postgres và ollama (chưa cần api/streamlit). Hướng dẫn pull model `frob/qwen3.5-instruct:4b`.
4. Schema PostgreSQL đúng mục 5 (SQLAlchemy models + cách tạo bảng), và app/db/seed.py nạp 8-10 công ty giả vào master_entities.
5. scripts/generate_dataset.py theo mục 11: 3 template, sinh 12-15 hợp đồng (DOCX + PDF có text layer) phủ đủ 6 kịch bản, kèm ground truth JSON. Dữ liệu công ty trong hợp đồng phải khớp/lệch với seed đúng theo từng kịch bản.

Không làm: parser, extraction, agent, API.
Kiểm chứng: docker compose up chạy được postgres + ollama; seed xong query được dữ liệu; mở thử 2-3 file PDF sinh ra để chắc chắn copy được chữ tiếng Việt.
Xong thì báo cáo theo mục 13.
```

Bạn phải tự giải thích được: vì sao dữ liệu hợp đồng và seed DB phải sinh từ cùng một nguồn; mỗi kịch bản trong ma trận kiểm tra điều gì.

---

### Tuần 2: Parse, Extraction và bản end-to-end mỏng

```
Đọc AGENTS.md và docs/ROADMAP.md. Hôm nay làm TUẦN 2.

Việc cần làm:
1. app/parsing/document_parser.py: PDF (pdfplumber) và DOCX (python-docx) -> list chunk {chunk_id, page, text}. DOCX: page = None, chunk theo đoạn. Ghi rõ trong comment cách chia chunk và vì sao.
2. app/extraction/schema.py: ExtractedField, RawExtraction đúng mục 6.
3. app/llm/client.py (client tương thích OpenAI, đọc .env) và app/llm/prompts.py. Prompt phải dặn: không có thông tin thì trả null; quote phải chép nguyên văn từ tài liệu; mỗi field một quote, ngắn nhất có thể nhưng kèm nhãn đi cùng giá trị (ví dụ "Mã số thuế: 0312345678").
4. app/extraction/extractor.py: gọi LLM, validate bằng Pydantic, nếu JSON sai cấu trúc thì thử lại tối đa 2 lần.
5. scripts/run_eval.py bản đầu: chạy parser + extractor trên toàn bộ data/contracts, so với ground truth, in độ chính xác từng field. Đây là baseline CHƯA có verifier. Yêu cầu thêm:
   - Lưu kết quả ra file để so sánh ở tuần 7.
   - Ghi thời gian xử lý từng file (parse và LLM riêng).
   - Lưu output thô của LLM cho từng file vào data/runs/<timestamp>/ để debug (thêm thư mục này vào .gitignore).
   - Việc chuẩn hóa giá trị để so với ground truth chỉ viết hàm tạm đơn giản ngay trong script này. KHÔNG đặt vào app/guardrails/, vì normalizers chính thức làm ở Tuần 3.
6. pytest cho parser (PDF và DOCX).

Không làm: verifier, LangGraph, DB reconciliation, API.
Nếu có nhiều cách hợp lý (ví dụ cách chia chunk, cách ép JSON), nêu 2-3 lựa chọn ngắn gọn và hỏi mình chọn trước khi code.
Kiểm chứng: chạy run_eval.py trên toàn bộ tập dev; pytest pass.
Xong thì báo cáo theo mục 13, kèm: bảng độ chính xác baseline theo từng field, thời gian trung bình mỗi file, và 5-8 ca sai điển hình (file, trường, giá trị đúng, giá trị model trả, quote model đưa) dựa trên dữ liệu thật, không đoán.
```

Bạn phải tự giải thích được: vì sao quote phải nguyên văn; vì sao field không có thì phải trả `null`; baseline này dùng để làm gì.

---

### Tuần 3: CitationVerifier

```
Đọc AGENTS.md (đặc biệt mục 8 và mục 14) và docs/ROADMAP.md. Hôm nay làm TUẦN 3.

Việc cần làm:
1. app/guardrails/normalizers.py: normalize_text, parse_vnd (+ trích số tiền ứng viên), parse_vn_date (+ trích ngày ứng viên), normalize_tax_code, normalize_company_name. Unit test cho từng hàm, nhiều định dạng khác nhau.
2. app/guardrails/citation_verifier.py đúng đặc tả mục 8: chuẩn hóa chunk + bảng offset, partial_ratio_alignment, tính page/chunk_id bằng code, kiểm tra value-in-quote theo loại field, trả list[VerifiedField].
3. Test đủ các tình huống: quote thật + giá trị đúng; quote bịa; quote thật nhưng giá trị sai; field null; quote nằm xuyên ranh giới hai chunk.
4. Cập nhật scripts/run_eval.py: chạy thêm verifier trên kết quả extraction và in thống kê trạng thái field.

Yêu cầu riêng: mọi hàm trong verifier ngắn, tên rõ, comment tiếng Việt giải thích VÌ SAO (không chỉ làm gì). Không dùng LLM trong verifier.
Không làm: LangGraph, retry, reconciliation, API.
Xong thì báo cáo theo mục 13.
```

Bạn phải tự giải thích được: vì sao chỉ kiểm tra quote tồn tại là chưa đủ; vì sao page do code tính chứ không hỏi LLM; vì sao dùng `partial_ratio` thay vì `ratio`; vì sao không dùng LLM để kiểm tra LLM.

---

### Tuần 4: Agent với LangGraph

```
Đọc AGENTS.md (mục 7 và 14) và docs/ROADMAP.md. Hôm nay làm TUẦN 4.

Việc cần làm:
1. app/agent/state.py: ContractAuditState đúng mục 7.
2. app/agent/nodes.py: parse_node, extract_node, verify_citation_node, retry_extraction_node, generate_report_node. reconcile_db_node tạm là khung rỗng (chỉ ghi trace, chưa so DB) vì tuần 5 mới làm.
3. app/agent/graph.py: StateGraph với conditional edge sau verify (đúng luật mục 7: retry tối đa MAX_RETRIES, chỉ yêu cầu lại field lỗi, hết lượt thì sinh AuditItem NEEDS_HUMAN_REVIEW). Tôn trọng ENABLE_VERIFIER và ENABLE_RETRY từ cấu hình.
4. Mỗi node ghi trace_log {node, ts, summary, decision}.
5. Một script chạy graph trên 1 file từ command line, in ra trace_log và kết quả.
6. Test graph bằng LLM giả (mock): trích xuất sạch; field sai rồi retry thành công; retry hết lượt vẫn sai -> NEEDS_HUMAN_REVIEW; ENABLE_RETRY=false; ENABLE_VERIFIER=false.

Không làm: reconciliation thật, API, UI.
Xong thì báo cáo theo mục 13, kèm một sơ đồ StateGraph dạng mermaid hoặc ASCII.
```

Bạn phải tự giải thích được: vì sao dùng LangGraph thay vì viết chuỗi hàm thường; vì sao giới hạn số lần retry; điều gì xảy ra với field vẫn sai sau khi retry hết lượt.

---

### Tuần 5: Reconciliation và API

```
Đọc AGENTS.md (mục 9, 10, 14) và docs/ROADMAP.md. Hôm nay làm TUẦN 5.

Việc cần làm:
1. app/reconciliation/engine.py đúng mục 9 (tìm theo MST, tên mờ, đại diện, hạn mức, 4 loại error_type, ghi audit_logs). Nối vào reconcile_db_node thay cho khung rỗng; xác định overall_result theo luật ưu tiên trong mục 7.
2. Lưu kết quả vào contracts / contract_entities / audit_logs, lưu trace_log.
3. FastAPI đúng mục 10: upload, process (BackgroundTasks, trả 202), result (có include_trace), healthz. Xử lý lỗi với đúng mã HTTP.
4. Test: reconciliation đủ các trường hợp (khớp, sai MST, sai đại diện, vượt hạn mức, không tồn tại, thiếu MST); test API cơ bản (sai định dạng, flow upload -> process -> result).
5. Chạy graph end-to-end trên toàn bộ bộ mẫu và in bảng: file, scenario, overall_result thực tế vs kỳ vọng.

Không làm: UI, Dockerfile cho api, evaluation đầy đủ.
Xong thì báo cáo theo mục 13.
```

Bạn phải tự giải thích được: vì sao đối soát không dùng LLM; vì sao chuẩn hóa tên công ty trước khi so mờ; khác nhau giữa `ENTITY_NOT_FOUND` và `IDENTITY_MISMATCH`.

---

### Tuần 6: UI tối thiểu và gói đưa vào CV

```
Đọc AGENTS.md và docs/ROADMAP.md. Hôm nay làm TUẦN 6.

Việc cần làm:
1. ui/streamlit_app.py tối thiểu: màn upload (gọi API), hiển thị trạng thái xử lý (polling); màn kết quả: overall_result, bảng các field (tô đỏ field sai lệch / cần review), bấm vào field xem quote nguồn và vị trí (page/chunk).
2. Dockerfile cho api và ui, cập nhật docker-compose.yml để chạy toàn bộ (api, postgres, ollama, streamlit) bằng một lệnh. Chạy seed tự động hoặc có lệnh rõ ràng.
3. Nháp README: mô tả bài toán 2-3 câu, sơ đồ kiến trúc, hướng dẫn chạy, mục Known Limitations (PDF scan, một loại tài liệu, chưa xử lý hàng loạt). Chừa trống mục "Design Decisions" cho mình tự viết.

Không làm: thêm tính năng ngoài UI tối thiểu.
Xong thì báo cáo theo mục 13, kèm các bước để mình quay video demo 2-3 phút (kịch bản đề xuất: 1 file sạch, 1 file sai MST, 1 file thiếu trường).
```

Bạn phải tự làm: viết mục **Design Decisions** trong README bằng lời của mình (vì sao LangGraph; vì sao verify bằng quote + value-in-quote; vì sao retry có giới hạn). Quay video demo. Đẩy repo lên GitHub public. Sau bước này có thể đưa vào CV.

---

### Tuần 7: Evaluation và Dockerize hoàn chỉnh

```
Đọc AGENTS.md (mục 11 và 12) và docs/ROADMAP.md. Hôm nay làm TUẦN 7.

Việc cần làm:
1. Mở rộng generate_dataset.py: thêm template mới và các ca khó (thông tin mâu thuẫn trong cùng tài liệu, định dạng ngày/số tiền lạ), nâng bộ dữ liệu lên 25-30 file kèm ground truth.
2. Hoàn thiện scripts/run_eval.py theo mục 12: (1) end-to-end với LLM thật, (2) stress test verifier bằng cách tự làm hỏng trích xuất đúng (sửa quote, đổi giá trị, bịa quote) rồi đo precision/recall, (3) ablation (a)/(b)/(c) qua cờ cấu hình. Xuất kết quả ra CSV và bảng markdown.
3. Không đặt chỉ tiêu cứng. Báo cáo số đo thật, và liệt kê 5-10 ca sai điển hình kèm nguyên nhân phỏng đoán (dựa trên dữ liệu, không bịa).
4. Kiểm tra lại docker compose up trên môi trường sạch, sửa lỗi phát sinh.

Không làm: thêm tính năng mới cho hệ thống.
Xong thì báo cáo theo mục 13.
```

Bạn phải tự giải thích được: ablation nói lên điều gì về từng thành phần; vì sao stress test verifier có đáp án rõ ràng hơn đo "ảo giác tự nhiên"; con số nào đáng tin và con số nào chỉ mang tính tham khảo (bộ dữ liệu nhỏ, do mình tự sinh).

---

### Tuần 8: Hoàn thiện báo cáo và slide

```
Đọc AGENTS.md và docs/ROADMAP.md. Hôm nay làm TUẦN 8.

Việc cần làm (không đụng vào logic hệ thống):
1. Dựa trên code và kết quả evaluation thực tế, xuất các sơ đồ cho báo cáo (mermaid): kiến trúc tổng thể, StateGraph, sequence diagram của luồng upload -> process -> result.
2. Tóm tắt kết quả evaluation thành bảng sẵn để dán vào Chương 4.
3. Gợi ý dàn ý slide 15-20 trang (kiến trúc, cơ chế chống ảo giác, demo, bảng ablation, hạn chế, hướng phát triển) và danh sách câu hỏi phản biện có thể gặp kèm gợi ý ý chính để trả lời.
4. Rà README: kiểm tra hướng dẫn chạy còn đúng với code hiện tại.

Không viết hộ toàn bộ báo cáo: mình sẽ tự viết nội dung các chương, bạn chỉ hỗ trợ sơ đồ, bảng số liệu, và rà soát lỗi.
```

---

## C. Prompt dùng giữa các tuần

**Gỡ lỗi (đưa đúng thông tin AI cần):**

```
Mình đang làm [tuần N]. Lỗi: [dán nguyên văn lỗi/traceback].
Lệnh đã chạy: [lệnh]. Kỳ vọng: [...]. Thực tế: [...].
Trước khi sửa, hãy giải thích nguyên nhân bằng lời, chỉ ra file/dòng liên quan, rồi đề xuất cách sửa nhỏ nhất.
Không refactor thứ không liên quan. Sau khi sửa, chạy lại test liên quan và báo kết quả.
```

**Tự học để phỏng vấn (dùng sau mỗi tuần):**

```
Mình sắp phải giải thích phần [tên module/file] khi phỏng vấn.
Hãy hỏi mình 5 câu về thiết kế và quyết định kỹ thuật của phần này, từng câu một, đợi mình trả lời rồi mới góp ý và hỏi câu tiếp.
Chỉ ra chỗ mình trả lời sai hoặc thiếu so với code thật trong repo.
```

**Review code trước khi commit:**

```
Review thay đổi hiện tại (git diff) theo AGENTS.md: có làm ngoài phạm vi tuần này không, có vi phạm quyết định ở mục 14 không, có chỗ nào nuốt lỗi, hardcode secret, thiếu test không.
Liệt kê vấn đề theo mức độ nghiêm trọng. Chưa sửa gì khi mình chưa đồng ý.
```
