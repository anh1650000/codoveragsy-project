"""Kiểm tra nhanh toàn bộ stack đang chạy qua HTTP: healthz -> upload -> process -> polling -> kiểm tra cấu trúc."""

import argparse
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_FILE = ROOT / "data" / "contracts" / "hd_001.pdf"
VALID_OVERALL_RESULTS = {"CLEAN", "NEEDS_REVIEW", "DISCREPANCY_FOUND"}


def validate_result_payload(payload: dict) -> list[str]:
    """Kiểm tra cấu trúc tối thiểu của kết quả trả về từ GET /api/v1/audit/result/{id}."""
    errors: list[str] = []
    if payload.get("status") != "DONE":
        errors.append(f"Trạng thái kỳ vọng DONE nhưng nhận: {payload.get('status')!r}")
    if payload.get("overall_result") not in VALID_OVERALL_RESULTS:
        errors.append(f"overall_result không hợp lệ: {payload.get('overall_result')!r}")
    if not isinstance(payload.get("fields"), list) or len(payload["fields"]) == 0:
        errors.append("Danh sách fields bị thiếu hoặc rỗng.")
    if not isinstance(payload.get("audit_items"), list):
        errors.append("audit_items không phải dạng danh sách (list).")
    return errors


def _format_http_error(response: httpx.Response) -> str:
    try:
        data = response.json()
        if isinstance(data, dict) and data.get("detail"):
            return str(data["detail"])
    except ValueError:
        pass
    return response.text.strip() or f"HTTP {response.status_code}"


def run_smoke_test(
    base_url: str,
    file_path: Path,
    timeout_seconds: float,
    poll_interval: float,
) -> int:
    """Thực thi smoke test qua HTTP và trả mã thoát (0 nếu đạt, 1 nếu lỗi)."""
    base = base_url.rstrip("/")
    if not file_path.is_file():
        print(f"[LỖI] Không tìm thấy file mẫu: {file_path}")
        return 1

    mime_type = (
        "application/pdf"
        if file_path.suffix.lower() == ".pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    http_timeout = httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=10.0)

    try:
        with httpx.Client(timeout=http_timeout) as client:
            # 1. Health check
            print(f"[1/4] Kiểm tra healthz tại {base}/api/v1/healthz ...")
            health_res = client.get(f"{base}/api/v1/healthz")
            if health_res.status_code != 200:
                print(f"[LỖI] Health check thất bại ({health_res.status_code}): {_format_http_error(health_res)}")
                return 1
            print(f"      OK: {health_res.json()}")

            # 2. Upload
            print(f"[2/4] Tải lên hợp đồng mẫu: {file_path.name} ...")
            with file_path.open("rb") as fh:
                upload_res = client.post(
                    f"{base}/api/v1/contracts/upload",
                    files={"file": (file_path.name, fh, mime_type)},
                )
            if upload_res.status_code >= 400:
                print(f"[LỖI] Upload thất bại ({upload_res.status_code}): {_format_http_error(upload_res)}")
                return 1
            contract_id = upload_res.json()["contract_id"]
            print(f"      OK: contract_id={contract_id}")

            # 3. Trigger process
            print(f"[3/4] Kích hoạt xử lý cho contract_id={contract_id} ...")
            proc_res = client.post(f"{base}/api/v1/audit/process/{contract_id}")
            if proc_res.status_code >= 400:
                print(f"[LỖI] Kích hoạt xử lý thất bại ({proc_res.status_code}): {_format_http_error(proc_res)}")
                return 1
            print(f"      OK: {proc_res.json()}")

            # 4. Polling
            print(f"[4/4] Đang polling kết quả (timeout={int(timeout_seconds)}s, chu kỳ={poll_interval}s) ...")
            started = time.monotonic()
            while True:
                elapsed = time.monotonic() - started
                result_res = client.get(
                    f"{base}/api/v1/audit/result/{contract_id}",
                    params={"include_trace": "true"},
                )
                if result_res.status_code >= 400:
                    print(f"[LỖI] Lấy kết quả thất bại ({result_res.status_code}): {_format_http_error(result_res)}")
                    return 1

                payload = result_res.json()
                status = payload.get("status")
                if status == "DONE":
                    errors = validate_result_payload(payload)
                    if errors:
                        print("[LỖI] Kết quả không đạt kiểm tra cấu trúc:")
                        for err in errors:
                            print(f"  - {err}")
                        return 1
                    print(
                        f"      HOÀN TẤT sau {elapsed:.1f}s | overall_result={payload['overall_result']} | "
                        f"fields={len(payload['fields'])} | audit_items={len(payload['audit_items'])} | "
                        f"retry_count={payload.get('retry_count')}"
                    )
                    return 0

                if status == "FAILED":
                    print(f"[LỖI] Hợp đồng FAILED sau {elapsed:.1f}s: {payload.get('error_message')}")
                    return 1

                if elapsed >= timeout_seconds:
                    print(
                        f"[LỖI] Quá thời gian chờ {int(timeout_seconds)}s "
                        f"(trạng thái hiện tại: {status}, contract_id={contract_id})."
                    )
                    return 1

                print(f"      ... trạng thái={status}, đã chờ {int(elapsed)}s")
                time.sleep(poll_interval)
    except httpx.HTTPError as error:
        print(f"[LỖI] Không kết nối được tới API ({base}): {error}")
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test qua HTTP cho stack FastAPI + DB + LLM.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", DEFAULT_BASE_URL),
        help="Địa chỉ gốc của API (mặc định đọc từ API_BASE_URL hoặc http://localhost:8000).",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_FILE,
        help="Đường dẫn tới hợp đồng mẫu để kiểm thử (mặc định: data/contracts/hd_001.pdf).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("SMOKE_TEST_TIMEOUT_SECONDS", "600")),
        help="Thời gian chờ tối đa tính bằng giây (mặc định từ SMOKE_TEST_TIMEOUT_SECONDS hoặc 600).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.getenv("UI_POLL_INTERVAL_SECONDS", "2")),
        help="Chu kỳ polling tính bằng giây (mặc định từ UI_POLL_INTERVAL_SECONDS hoặc 2).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = run_smoke_test(
        base_url=args.base_url,
        file_path=args.file,
        timeout_seconds=args.timeout,
        poll_interval=args.poll_interval,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
