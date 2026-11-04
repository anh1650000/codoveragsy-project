"""Đo baseline extraction trên bộ hợp đồng, chưa chạy CitationVerifier."""

import csv
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.extraction.extractor import ExtractionError, extract_fields
from app.parsing.document_parser import parse_document

CONTRACTS_DIR = ROOT / "data" / "contracts"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"
FIELDS = (
    "party_a_name",
    "party_b_name",
    "party_b_tax_code",
    "party_b_legal_representative",
    "contract_value",
    "effective_date",
    "payment_terms",
)


def normalize_for_comparison(field_name: str, value: object) -> str | None:
    """Chuẩn hóa tạm để so baseline; normalizer chính thức thuộc Tuần 3."""
    if value is None:
        return None
    text = " ".join(str(value).lower().split())
    if field_name in {"party_b_tax_code", "contract_value"}:
        digits = "".join(re.findall(r"\d", text))
        return digits or text
    if field_name == "effective_date":
        written = re.fullmatch(r"(?:ngày\s+)?(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", text)
        numeric = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
        try:
            if written:
                day, month, year = map(int, written.groups())
                return date(year, month, day).isoformat()
            if numeric:
                day, month, year = map(int, numeric.groups())
                return date(year, month, day).isoformat()
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return text
    if field_name == "payment_terms":
        text = re.sub(r"^thời hạn thanh toán:\s*", "", text)
    return text.strip(" .;:")


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
                "correct": normalize_for_comparison(field_name, expected)
                == normalize_for_comparison(field_name, actual),
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


def main() -> None:
    run_name = time.strftime("%Y%m%d_%H%M%S")
    run_dir = ROOT / "data" / "runs" / run_name
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


if __name__ == "__main__":
    main()
