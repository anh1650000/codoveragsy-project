"""Chạy LangGraph Contract Audit Agent trên một file hợp đồng từ dòng lệnh."""

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.graph import build_contract_audit_graph, make_initial_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chạy pipeline LangGraph (Parse -> Extract -> Verify -> Retry -> Reconcile -> Report) trên 1 file."
    )
    parser.add_argument("file_path", type=Path, help="Đường dẫn tới file hợp đồng PDF hoặc DOCX.")
    parser.add_argument(
        "--contract-id",
        type=int,
        default=0,
        help="ID hợp đồng giả lập khi chạy CLI chưa gắn DB (mặc định: 0).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    target_path = args.file_path
    if not target_path.is_absolute() and not target_path.exists():
        candidate = PROJECT_ROOT / target_path
        if candidate.exists():
            target_path = candidate

    graph = build_contract_audit_graph()
    initial_state = make_initial_state(target_path, contract_id=args.contract_id)

    started = time.perf_counter()
    final_state = graph.invoke(initial_state)
    elapsed = time.perf_counter() - started

    print(f"=== Kết quả chạy graph: {target_path} ===")
    print(f"Thời gian xử lý: {elapsed:.2f}s | Số lần retry: {final_state['retry_count']}")
    print(f"Kết luận tổng thể (overall_result): {final_state['overall_result']}")

    print("\n--- Trace log ---")
    for idx, entry in enumerate(final_state["trace_log"], start=1):
        print(
            f"{idx}. [{entry['ts']}] {entry['node']} | {entry['summary']} | decision: {entry['decision']}"
        )

    print("\n--- Verified fields ---")
    for vf in final_state["verified_fields"]:
        score_text = f"{vf.match_score:.1f}" if vf.match_score is not None else "-"
        print(
            f"- {vf.name}: status={vf.status.value} | score={score_text} | "
            f"page={vf.page} | chunk={vf.chunk_id}\n"
            f"    value={vf.value!r}\n"
            f"    quote={vf.quote!r}"
        )

    print("\n--- Audit items ---")
    if not final_state["audit_items"]:
        print("Không có cảnh báo.")
    else:
        for item in final_state["audit_items"]:
            print(
                f"- [{item.error_type}] field={item.field_name} | "
                f"extracted={item.extracted_value!r} | detail={item.detail}"
            )


if __name__ == "__main__":
    main()
