# Contract & Document Verification Agent System

Repo niên luận xây dựng hệ thống đọc hợp đồng, trích xuất thông tin kèm trích dẫn, kiểm chứng bằng code và đối soát dữ liệu doanh nghiệp.

## Tuần 1: khởi tạo môi trường

1. Cài Python 3.11+, Docker Desktop và Ollama trên máy chính.
2. Tạo file cấu hình: `Copy-Item .env.example .env` (PowerShell).
3. Cài thư viện: `python -m pip install -r requirements.txt`.
4. Khởi động PostgreSQL: `docker compose up -d`.
5. Tải model vào Ollama trên máy chính: `ollama pull frob/qwen3.5-instruct:4b`; kiểm tra bằng `ollama list`.
6. Tạo bảng và nạp 10 công ty giả: `python -m app.db.seed`.
7. Sinh hợp đồng mẫu: `python scripts/generate_dataset.py`.

Ứng dụng và scripts chạy trực tiếp trên máy gọi Ollama tại `http://localhost:11434/v1`. Docker Compose chỉ chạy PostgreSQL. Không chạy Ollama container song song cho project này.

Kiểm tra dữ liệu seed bằng lệnh:

```powershell
docker compose exec postgres psql -U contracts -d contracts -c "SELECT vat_code, company_name, legal_representative, max_contract_value FROM master_entities ORDER BY vat_code;"
```

## Đo tốc độ model

Model phát triển đã chốt là `frob/qwen3.5-instruct:4b`; cấu hình `.env` dùng `LLM_BASE_URL=http://localhost:11434/v1` và `LLM_MODEL=frob/qwen3.5-instruct:4b`. Model này chưa có trên Ollama máy chính; lệnh pull bị dừng do tốc độ tải không ổn định. Host hiện đã có `qwen3.5:4b` và `qwen3.5:9b`. Kiểm tra endpoint host bằng model có sẵn `qwen3.5:4b` đạt 67 tokens trong 34,88 giây (1,92 tokens/giây); Ollama dùng 52% CPU và 48% GPU. Để đo model đã chốt sau khi pull thành công, bảo đảm Ollama trên máy đang chạy model rồi thực hiện:

```powershell
python scripts/check_llm_speed.py
```

Script ghi thời gian, completion tokens và tokens/giây nếu Ollama trả usage.

## Dữ liệu mẫu

`python scripts/generate_dataset.py` tạo 12 hợp đồng (6 PDF có text layer và 6 DOCX) cùng JSON ground truth trong `data/ground_truth/`. Sáu kịch bản được phủ hai lần mỗi loại. Dữ liệu đều giả; seed database và hợp đồng cùng lấy thông tin chuẩn từ `app/db/seed_data.py`.

