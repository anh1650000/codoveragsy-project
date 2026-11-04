"""Sinh 12 hợp đồng giả, mỗi hồ sơ có một DOCX hoặc PDF và ground truth."""

import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from docx import Document
from docx.shared import Pt
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.seed_data import MASTER_ENTITIES

CONTRACTS_DIR = ROOT / "data" / "contracts"
GROUND_TRUTH_DIR = ROOT / "data" / "ground_truth"


@dataclass(frozen=True)
class ScenarioCase:
    """Một hồ sơ mẫu cùng thông tin mong đợi."""

    scenario: str
    entity_index: int
    extension: str
    variant: int


CASES = [
    ScenarioCase("CLEAN", 0, ".pdf", 0),
    ScenarioCase("CLEAN", 1, ".docx", 1),
    ScenarioCase("WRONG_TAX_CODE", 2, ".pdf", 2),
    ScenarioCase("WRONG_TAX_CODE", 3, ".docx", 0),
    ScenarioCase("WRONG_REPRESENTATIVE", 4, ".pdf", 1),
    ScenarioCase("WRONG_REPRESENTATIVE", 5, ".docx", 2),
    ScenarioCase("OVER_LIMIT", 6, ".pdf", 0),
    ScenarioCase("OVER_LIMIT", 7, ".docx", 1),
    ScenarioCase("UNKNOWN_ENTITY", 8, ".pdf", 2),
    ScenarioCase("UNKNOWN_ENTITY", 9, ".docx", 0),
    ScenarioCase("MISSING_FIELD", 0, ".pdf", 1),
    ScenarioCase("MISSING_FIELD", 1, ".docx", 2),
]

TEMPLATES = [
    {
        "title": "HỢP ĐỒNG CUNG CẤP DỊCH VỤ",
        "date": "ngày {day} tháng {month} năm {year}",
        "amount": "{amount} đồng (bằng chữ: theo thỏa thuận của hai bên)",
        "payment": "Bên A thanh toán trong vòng 15 ngày kể từ ngày nghiệm thu.",
    },
    {
        "title": "HỢP ĐỒNG KINH TẾ SỐ {number}/2026/HĐKT",
        "date": "{day:02d}/{month:02d}/{year}",
        "amount": "VND {amount}",
        "payment": "Thanh toán thành hai đợt sau khi bàn giao và nghiệm thu.",
    },
    {
        "title": "THỎA THUẬN THỰC HIỆN CÔNG VIỆC",
        "date": "{day:02d}-{month:02d}-{year}",
        "amount": "{amount} VNĐ",
        "payment": "Thời hạn thanh toán: 30 ngày từ khi nhận đủ hồ sơ.",
    },
]

UNKNOWN_ENTITY = {
    "vat_code": "0399999999",
    "company_name": "Công ty TNHH Sao Biển",
    "legal_representative": "Mai Hoàng Phúc",
    "max_contract_value": 750_000_000,
}
WRONG_REPRESENTATIVES = ["Nguyễn Văn Lạ", "Lâm Quốc Khánh"]


def format_vnd(value: int) -> str:
    """Dùng dấu chấm phân nhóm nghìn theo cách viết phổ biến tại Việt Nam."""
    return f"{value:,}".replace(",", ".")


def create_contract_data(case: ScenarioCase, contract_number: int) -> tuple[str, dict]:
    """Tạo nội dung hồ sơ và đáp án đã chuẩn hóa từ cùng dữ liệu nguồn."""
    template = TEMPLATES[case.variant]
    if case.scenario == "UNKNOWN_ENTITY":
        entity = UNKNOWN_ENTITY
    else:
        entity = MASTER_ENTITIES[case.entity_index]

    tax_code = entity["vat_code"]
    representative = entity["legal_representative"]
    value = min(500_000_000, entity["max_contract_value"])
    if case.scenario == "WRONG_TAX_CODE":
        tax_code = f"039{contract_number:07d}"
    if case.scenario == "WRONG_REPRESENTATIVE":
        representative = WRONG_REPRESENTATIVES[case.entity_index % len(WRONG_REPRESENTATIVES)]
    if case.scenario == "OVER_LIMIT":
        value = entity["max_contract_value"] + 250_000_000
    if case.scenario == "MISSING_FIELD":
        tax_code = None

    year, month, day = 2026, 3 + (contract_number % 8), 1 + (contract_number % 25)
    date_text = template["date"].format(day=day, month=month, year=year, number=contract_number)
    title = template["title"].format(number=contract_number)
    party_a_name = "Công ty TNHH Giải pháp Mekong"
    amount_text = template["amount"].format(amount=format_vnd(value))
    tax_line = f"Mã số thuế: {tax_code}." if tax_code else None
    lines = [
        title,
        f"Số: {contract_number:03d}/2026/HĐDV",
        f"Hôm nay, {date_text}, các bên gồm:",
        f"BÊN A: {party_a_name}",
        f"BÊN B: {entity['company_name']}",
    ]
    if tax_line:
        lines.append(tax_line)
    lines.extend(
        [
            f"Người đại diện: {representative}.",
            f"Giá trị hợp đồng: {amount_text}.",
            template["payment"],
            "Hai bên thống nhất thực hiện đúng các điều khoản của hợp đồng này.",
        ]
    )
    body = "\n".join(lines)
    truth = {
        "file": f"hd_{contract_number:03d}{case.extension}",
        "template": f"T{case.variant + 1}",
        "scenario": case.scenario,
        "fields": {
            "party_a_name": party_a_name,
            "party_b_name": entity["company_name"],
            "party_b_tax_code": tax_code,
            "party_b_legal_representative": representative,
            "contract_value": value,
            "effective_date": date(year, month, day).isoformat(),
            "payment_terms": template["payment"],
        },
        "expected_overall_result": expected_result(case.scenario),
        "expected_audit_error_types": expected_errors(case.scenario),
    }
    return body, truth


def expected_result(scenario: str) -> str:
    """Gán kết quả kịch bản theo ma trận đã chốt trong đặc tả."""
    if scenario == "CLEAN":
        return "CLEAN"
    if scenario == "MISSING_FIELD":
        return "NEEDS_REVIEW"
    return "DISCREPANCY_FOUND"


def expected_errors(scenario: str) -> list[str]:
    """Gán loại cảnh báo mong đợi cho từng kịch bản."""
    return {
        "CLEAN": [],
        "WRONG_TAX_CODE": ["IDENTITY_MISMATCH"],
        "WRONG_REPRESENTATIVE": ["IDENTITY_MISMATCH"],
        "OVER_LIMIT": ["VALUE_OVER_LIMIT"],
        "UNKNOWN_ENTITY": ["ENTITY_NOT_FOUND"],
        "MISSING_FIELD": ["NEEDS_HUMAN_REVIEW"],
    }[scenario]


def find_vietnamese_font() -> Path:
    """Chọn font TrueType có glyph tiếng Việt để PDF giữ được lớp văn bản."""
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/times.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Không tìm thấy font TrueType có tiếng Việt. Cài Arial/DejaVu Sans rồi chạy lại."
    )


def write_docx(path: Path, body: str) -> None:
    """Ghi từng dòng thành đoạn văn để tài liệu dễ đọc và có thể parse sau này."""
    document = Document()
    normal_style = document.styles["Normal"]
    normal_style.font.name = "Arial"
    normal_style.font.size = Pt(12)
    for line in body.splitlines():
        document.add_paragraph(line)
    document.save(path)


def write_pdf(path: Path, body: str, font_path: Path) -> None:
    """Vẽ chữ Unicode thật vào PDF, không raster hóa thành ảnh."""
    font_name = "VietnameseFont"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    pdf = canvas.Canvas(str(path), pagesize=A4)
    page_width, page_height = A4
    margin = 54
    y = page_height - margin
    pdf.setFont(font_name, 12)
    for line in body.splitlines():
        wrapped_lines = wrap_line(line, max_chars=86)
        for wrapped_line in wrapped_lines:
            if y < margin:
                pdf.showPage()
                pdf.setFont(font_name, 12)
                y = page_height - margin
            pdf.drawString(margin, y, wrapped_line)
            y -= 20
    pdf.save()


def wrap_line(line: str, max_chars: int) -> list[str]:
    """Ngắt dòng theo khoảng trắng để nội dung nằm gọn trong trang A4."""
    words = re.sub(r"\s+", " ", line).split(" ")
    wrapped: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            wrapped.append(current)
            current = word
        else:
            current = candidate
    if current:
        wrapped.append(current)
    return wrapped or [""]


def main() -> None:
    """Sinh hợp đồng DOCX/PDF và ground truth cùng tên file."""
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    font_path = find_vietnamese_font() if any(case.extension == ".pdf" for case in CASES) else None

    for contract_number, case in enumerate(CASES, start=1):
        body, truth = create_contract_data(case, contract_number)
        contract_path = CONTRACTS_DIR / truth["file"]
        if case.extension == ".pdf":
            assert font_path is not None
            write_pdf(contract_path, body, font_path)
        else:
            write_docx(contract_path, body)
        ground_truth_path = GROUND_TRUTH_DIR / f"{contract_path.name}.json"
        ground_truth_path.write_text(
            json.dumps(truth, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Đã tạo {contract_path.relative_to(ROOT)} và {ground_truth_path.relative_to(ROOT)}")

    print(f"Hoàn tất {len(CASES)} hợp đồng ({sum(c.extension == '.pdf' for c in CASES)} PDF).")


if __name__ == "__main__":
    main()
