"""Đánh giá extraction baseline và chạy kiểm chứng CitationVerifier trên tập hợp đồng."""

import argparse
import csv
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.extraction.extractor import ExtractionError, _clean_json_text, extract_fields
from app.extraction.schema import FieldStatus, RawExtraction, VerifiedField
from app.guardrails.citation_verifier import CitationVerifier
from app.guardrails.normalizers import (
    normalize_company_name,
    normalize_person_name,
    normalize_tax_code,
    normalize_text,
    parse_money,
    parse_vn_date,
)
from app.parsing.document_parser import parse_document

CONTRACTS_DIR = ROOT / "data" / "contracts"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"
RUNS_DIR = ROOT / "data" / "runs"
FIELDS = (
    "party_a_name",
    "party_b_name",
    "party_b_tax_code",
    "party_b_legal_representative",
    "contract_value",
    "effective_date",
    "payment_terms",
)
SCORE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("<70", 0.0, 70.0),
    ("70-<80", 70.0, 80.0),
    ("80-<85", 80.0, 85.0),
    ("85-<95", 85.0, 95.0),
    ("95-100", 95.0, 100.0001),
)


def normalize_for_comparison(field_name: str, value: object) -> str | None:
    """Chuẩn hóa giá trị về dạng đồng nhất để đối chiếu với ground truth."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        return None

    if field_name == "party_b_tax_code":
        return normalize_tax_code(text) or normalize_text(text)
    if field_name == "contract_value":
        money = parse_money(text)
        return f"{money.amount} {money.currency}" if money is not None else normalize_text(text)
    if field_name == "effective_date":
        parsed_date = parse_vn_date(text)
        if parsed_date is not None:
            return parsed_date.isoformat()
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return normalize_text(text)
    if field_name in {"party_a_name", "party_b_name"}:
        return normalize_company_name(text)
    if field_name == "party_b_legal_representative":
        return normalize_person_name(text)
    if field_name == "payment_terms":
        cleaned = normalize_text(text)
        cleaned = re.sub(r"^(?:thời hạn thanh toán|điều khoản thanh toán):\s*", "", cleaned)
        return cleaned.strip(" .;:")
    return normalize_text(text).strip(" .;:")


def is_field_correct(field_name: str, expected: object, actual: object) -> bool:
    """So sánh giá trị trích xuất với ground truth sau khi chuẩn hóa."""
    if expected is None:
        return actual is None or str(actual).strip().lower() in {"", "none", "null"}
    if actual is None:
        return False
    norm_exp = normalize_for_comparison(field_name, expected)
    norm_act = normalize_for_comparison(field_name, actual)
    if norm_exp == norm_act:
        return True
    if field_name == "payment_terms" and norm_exp and norm_act:
        return norm_act in norm_exp or norm_exp in norm_act
    return False


def load_ground_truth(contract_name: str) -> dict:
    truth_path = GROUND_TRUTH_DIR / f"{contract_name}.json"
    return json.loads(truth_path.read_text(encoding="utf-8"))


def mark_extraction_failed(record: dict, truth: dict) -> None:
    """Tính file không có kết quả hợp lệ là sai ở cả bảy trường baseline."""
    for field_name in FIELDS:
        record["fields"][field_name] = {
            "expected": truth["fields"].get(field_name),
            "predicted": None,
            "quote": None,
            "correct": False,
        }


def evaluate_contract(contract_path: Path) -> dict:
    record: dict = {
        "file": contract_path.name,
        "scenario": None,
        "parse_seconds": None,
        "extraction_seconds": None,
        "fields": {},
        "raw_outputs": [],
        "error": None,
    }
    truth = None
    try:
        truth = load_ground_truth(contract_path.name)
        record["scenario"] = truth.get("scenario")
        started = time.perf_counter()
        chunks = parse_document(contract_path)
        record["parse_seconds"] = time.perf_counter() - started
    except Exception as error:
        record["error"] = f"parse/ground_truth: {type(error).__name__}: {error}"
        if truth is not None:
            mark_extraction_failed(record, truth)
        return record

    started = time.perf_counter()
    try:
        extraction, raw_outputs = extract_fields(chunks)
        record["raw_outputs"] = raw_outputs
        predicted = extraction.model_dump(mode="json")
        for field_name in FIELDS:
            expected = truth["fields"].get(field_name)
            actual = predicted[field_name]["value"]
            record["fields"][field_name] = {
                "expected": expected,
                "predicted": actual,
                "quote": predicted[field_name]["quote"],
                "correct": is_field_correct(field_name, expected, actual),
            }
    except ExtractionError as error:
        record["raw_outputs"] = error.raw_outputs
        record["error"] = f"extraction: {type(error).__name__}: {error}"
    except Exception as error:
        record["error"] = f"extraction: {type(error).__name__}: {error}"
    if record["error"] and not record["fields"]:
        mark_extraction_failed(record, truth)
    record["extraction_seconds"] = time.perf_counter() - started
    return record


def write_results(run_dir: Path, records: list[dict]) -> None:
    """Lưu output thô, kết quả từng file và thống kê dạng CSV cho tuần 7."""
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        raw_path = raw_dir / f"{record['file']}.json"
        raw_path.write_text(
            json.dumps(
                {"file": record["file"], "error": record["error"], "attempts": record["raw_outputs"]},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    (run_dir / "baseline.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (run_dir / "baseline.csv").open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=["file", "scenario", "parse_seconds", "extraction_seconds", "correct_fields", "total_fields", "error"],
        )
        writer.writeheader()
        for record in records:
            correct = sum(field["correct"] for field in record["fields"].values())
            writer.writerow(
                {
                    "file": record["file"],
                    "scenario": record["scenario"],
                    "parse_seconds": record["parse_seconds"],
                    "extraction_seconds": record["extraction_seconds"],
                    "correct_fields": correct,
                    "total_fields": len(FIELDS),
                    "error": record["error"],
                }
            )

    field_stats = []
    for field_name in FIELDS:
        values = [record["fields"][field_name] for record in records if field_name in record["fields"]]
        correct = sum(item["correct"] for item in values)
        field_stats.append(
            {"field": field_name, "correct": correct, "total": len(values), "accuracy": correct / len(values) if values else None}
        )
    with (run_dir / "field_accuracy.csv").open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=["field", "correct", "total", "accuracy"])
        writer.writeheader()
        writer.writerows(field_stats)


def find_latest_run_dir() -> Path:
    """Tìm thư mục run mới nhất trong data/runs/ có sẵn dữ liệu raw/*.json."""
    if not RUNS_DIR.is_dir():
        raise FileNotFoundError(f"Không tìm thấy thư mục runs: {RUNS_DIR}")
    candidates = sorted(
        (
            path
            for path in RUNS_DIR.iterdir()
            if path.is_dir() and (path / "raw").is_dir() and any((path / "raw").glob("*.json"))
        ),
        key=lambda p: p.name,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"Không tìm thấy dữ liệu raw/*.json trong {RUNS_DIR}")
    return candidates[0]


def _load_raw_extraction_from_file(raw_path: Path) -> RawExtraction:
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    attempts = payload.get("attempts") or []
    if not attempts:
        raise ValueError(f"Không có raw output trong {raw_path.name}")
    cleaned = _clean_json_text(str(attempts[-1]))
    return RawExtraction.model_validate(json.loads(cleaned))


def _summarize_scores(scores: list[float]) -> dict:
    buckets = {
        label: sum(1 for s in scores if low <= s < high)
        for label, low, high in SCORE_BUCKETS
    }
    if not scores:
        return {"count": 0, "min": None, "median": None, "max": None, "buckets": buckets}
    return {
        "count": len(scores),
        "min": round(min(scores), 2),
        "median": round(median(scores), 2),
        "max": round(max(scores), 2),
        "buckets": buckets,
    }


def evaluate_verifier_on_run(run_dir: Path, threshold: float | None = None) -> dict:
    """Chạy CitationVerifier trên output thô đã lưu trong run_dir và lập bảng phân tích."""
    raw_dir = run_dir / "raw"
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"Thiếu thư mục raw trong {run_dir}")

    verifier = CitationVerifier(threshold=threshold)
    raw_files = sorted(raw_dir.glob("*.json"))
    status_counts = {status.value: 0 for status in FieldStatus}
    crosstab = {
        status.value: {"correct": 0, "wrong": 0}
        for status in FieldStatus
    }
    false_positives: list[dict] = []  # Đúng GT nhưng verifier báo lỗi (bắt oan).
    false_negatives: list[dict] = []  # Sai GT nhưng verifier cho VERIFIED (lọt lưới).
    correct_scores: list[float] = []
    wrong_scores: list[float] = []
    file_records: list[dict] = []

    for raw_path in raw_files:
        contract_name = raw_path.name.removesuffix(".json")
        contract_path = CONTRACTS_DIR / contract_name
        truth = load_ground_truth(contract_name)
        chunks = parse_document(contract_path)
        raw_extraction = _load_raw_extraction_from_file(raw_path)
        verified_fields: list[VerifiedField] = verifier.verify(raw_extraction, chunks)

        verified_entries: list[dict] = []
        for vf in verified_fields:
            expected = truth["fields"].get(vf.name)
            gt_correct = is_field_correct(vf.name, expected, vf.value)
            status_key = vf.status.value
            status_counts[status_key] += 1
            crosstab[status_key]["correct" if gt_correct else "wrong"] += 1

            if vf.match_score is not None:
                if gt_correct:
                    correct_scores.append(vf.match_score)
                else:
                    wrong_scores.append(vf.match_score)

            item_summary = {
                "file": contract_name,
                "field": vf.name,
                "expected": expected,
                "value": vf.value,
                "quote": vf.quote,
                "status": status_key,
                "match_score": vf.match_score,
                "page": vf.page,
                "chunk_id": vf.chunk_id,
                "gt_correct": gt_correct,
            }
            verified_entries.append(item_summary)

            if gt_correct and vf.status in {FieldStatus.QUOTE_NOT_FOUND, FieldStatus.VALUE_NOT_IN_QUOTE}:
                false_positives.append(item_summary)
            elif not gt_correct and vf.status == FieldStatus.VERIFIED:
                false_negatives.append(item_summary)

        file_records.append(
            {
                "file": contract_name,
                "scenario": truth.get("scenario"),
                "fields": verified_entries,
            }
        )

    report = {
        "run_dir": str(run_dir.relative_to(ROOT)),
        "threshold": verifier.threshold,
        "total_files": len(file_records),
        "total_fields": sum(status_counts.values()),
        "status_counts": status_counts,
        "crosstab": crosstab,
        "false_positives_bat_oan": false_positives,
        "false_negatives_lot_luoi": false_negatives,
        "score_distribution": {
            "correct_fields": _summarize_scores(correct_scores),
            "wrong_fields": _summarize_scores(wrong_scores),
        },
        "files": file_records,
    }
    (run_dir / "verifier_eval.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def print_verifier_report(report: dict) -> None:
    """In các bảng thống kê trạng thái, bảng chéo, ca lỗi và phân bố match_score."""
    print(f"\n=== Đánh giá CitationVerifier (offline) trên {report['run_dir']} ===")
    print(f"Ngưỡng CITATION_THRESHOLD: {report['threshold']} | Số file: {report['total_files']} | Tổng field: {report['total_fields']}")

    print("\n1. Thống kê số field theo trạng thái verifier:")
    for status in FieldStatus:
        count = report["status_counts"][status.value]
        ratio = count / report["total_fields"] if report["total_fields"] else 0.0
        print(f"  {status.value:<22} {count:>4} ({ratio:6.1%})")

    print("\n2. Bảng chéo: Trạng thái verifier vs Ground Truth (sau chuẩn hóa):")
    print(f"  {'Trạng thái':<22} {'Đúng GT':>9} {'Sai GT':>9} {'Tổng':>8}  Ghi chú")
    for status in FieldStatus:
        row = report["crosstab"][status.value]
        total = row["correct"] + row["wrong"]
        note = ""
        if status == FieldStatus.VERIFIED:
            note = "Sai GT = Lọt lưới"
        elif status in {FieldStatus.QUOTE_NOT_FOUND, FieldStatus.VALUE_NOT_IN_QUOTE}:
            note = "Đúng GT = Bắt oan"
        print(f"  {status.value:<22} {row['correct']:>9} {row['wrong']:>9} {total:>8}  {note}")

    print("\n3. Các ca Bắt oan (Đúng GT nhưng bị đánh dấu QUOTE_NOT_FOUND / VALUE_NOT_IN_QUOTE):")
    if not report["false_positives_bat_oan"]:
        print("  Không có ca nào.")
    else:
        for item in report["false_positives_bat_oan"]:
            print(
                f"  - {item['file']} | {item['field']} | status={item['status']} | "
                f"score={item['match_score']} | value={item['value']!r} | quote={item['quote']!r}"
            )

    print("\n4. Các ca Lọt lưới (Sai GT nhưng được gắn VERIFIED):")
    if not report["false_negatives_lot_luoi"]:
        print("  Không có ca nào.")
    else:
        for item in report["false_negatives_lot_luoi"]:
            print(
                f"  - {item['file']} | {item['field']} | expected={item['expected']!r} | "
                f"score={item['match_score']} | value={item['value']!r} | quote={item['quote']!r}"
            )

    print("\n5. Phân bố match_score (các field có quote được so khớp):")
    for label, key in (
        ("Quote của field Đúng GT", "correct_fields"),
        ("Quote của field Sai GT ", "wrong_fields"),
    ):
        dist = report["score_distribution"][key]
        if dist["count"] == 0:
            print(f"  {label}: 0 ca")
            continue
        bucket_text = ", ".join(f"{b}:{n}" for b, n in dist["buckets"].items())
        print(
            f"  {label}: n={dist['count']} | min={dist['min']} | median={dist['median']} | "
            f"max={dist['max']} | [{bucket_text}]"
        )


def run_live_baseline() -> Path:
    """Chạy parser + LLM extraction trực tiếp (Tuần 2) và lưu vào thư mục run mới."""
    run_name = time.strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    contract_paths = sorted(
        path for path in CONTRACTS_DIR.iterdir() if path.suffix.lower() in {".pdf", ".docx"}
    )
    if not contract_paths:
        raise FileNotFoundError(f"Không có PDF/DOCX trong {CONTRACTS_DIR}")

    records = []
    for index, contract_path in enumerate(contract_paths, start=1):
        print(f"[{index}/{len(contract_paths)}] {contract_path.name}", flush=True)
        record = evaluate_contract(contract_path)
        records.append(record)
        if record["error"]:
            print(f"  Lỗi: {record['error']}", flush=True)
        else:
            correct = sum(field["correct"] for field in record["fields"].values())
            print(
                f"  Đúng {correct}/{len(record['fields'])}; parse={record['parse_seconds']:.3f}s; "
                f"LLM={record['extraction_seconds']:.3f}s",
                flush=True,
            )

    write_results(run_dir, records)
    print("\nĐộ chính xác baseline theo trường (chưa có verifier):")
    print(f"{'Trường':38} {'Đúng/Tổng':12} {'Accuracy':>9}")
    for field_name in FIELDS:
        values = [record["fields"][field_name] for record in records if field_name in record["fields"]]
        correct = sum(item["correct"] for item in values)
        accuracy = correct / len(values) if values else 0
        print(f"{field_name:38} {correct:>3}/{len(values):<8} {accuracy:8.1%}")

    parse_times = [record["parse_seconds"] for record in records if record["parse_seconds"] is not None]
    llm_times = [record["extraction_seconds"] for record in records if record["extraction_seconds"] is not None]
    print(f"\nThời gian parse trung bình: {sum(parse_times) / len(parse_times):.3f}s/file" if parse_times else "Không có thời gian parse hợp lệ.")
    print(f"Thời gian LLM trung bình: {sum(llm_times) / len(llm_times):.3f}s/file" if llm_times else "Không có thời gian LLM hợp lệ.")
    print(f"Kết quả và output thô: {run_dir.relative_to(ROOT)}")
    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Đánh giá extraction và CitationVerifier.")
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Thư mục data/runs/<timestamp> có sẵn raw/*.json (mặc định: lấy lần chạy mới nhất).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Thử nghiệm ngưỡng CITATION_THRESHOLD tạm thời mà không sửa .env.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Gọi lại LLM trên tập hợp đồng trước khi chạy CitationVerifier.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.live:
        target_run_dir = run_live_baseline()
    else:
        target_run_dir = args.run_dir if args.run_dir is not None else find_latest_run_dir()
        if not target_run_dir.is_absolute():
            target_run_dir = ROOT / target_run_dir

    report = evaluate_verifier_on_run(target_run_dir, threshold=args.threshold)
    print_verifier_report(report)


if __name__ == "__main__":
    main()
