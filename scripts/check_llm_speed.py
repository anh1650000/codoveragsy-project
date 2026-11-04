"""Đo thời gian phản hồi và tốc độ sinh token qua API OpenAI-compatible."""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.llm.client import get_llm_client, get_llm_model


def main() -> None:
    """Gửi một yêu cầu trích xuất ngắn và in số đo trả về từ API."""
    client = get_llm_client()
    base_url = str(client.base_url)
    model = get_llm_model()
    prompt = (
        "Trích xuất tên bên B, mã số thuế và giá trị hợp đồng từ đoạn sau. "
        "Trả JSON ngắn, mỗi giá trị kèm quote nguyên văn.\n\n"
        "Bên B: Công ty TNHH An Phát, mã số thuế 0310000001. "
        "Giá trị hợp đồng là 500.000.000 đồng."
    )
    request_options = {}
    if "11434" in base_url or "ollama" in base_url.lower():
        # Endpoint /v1 dùng reasoning_effort để tắt thinking trên model hỗ trợ.
        request_options["extra_body"] = {"reasoning_effort": "none"}

    started_at = time.perf_counter()
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=256,
        **request_options,
    )
    elapsed_seconds = time.perf_counter() - started_at
    content = response.choices[0].message.content or ""
    usage = response.usage
    completion_tokens = getattr(usage, "completion_tokens", None) if usage else None

    print(f"Model: {model}")
    print(f"API: {base_url}")
    print(f"Thời gian yêu cầu: {elapsed_seconds:.2f} giây")
    if completion_tokens:
        print(f"Completion tokens: {completion_tokens}")
        print(f"Tốc độ sinh: {completion_tokens / elapsed_seconds:.2f} tokens/giây")
    else:
        print("API không trả completion_tokens; chưa thể tính tokens/giây.")
    print("\nPhản hồi mẫu:")
    print(content)


if __name__ == "__main__":
    main()


