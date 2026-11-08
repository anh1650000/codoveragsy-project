"""Đọc PDF có lớp chữ và DOCX thành các chunk văn bản có vị trí nguồn."""

from pathlib import Path

import pdfplumber
from docx import Document


def parse_document(file_path: str | Path) -> list[dict[str, int | None | str]]:
    """Trả về các chunk theo thứ tự tài liệu, mỗi chunk có id, trang và nội dung."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    if suffix == ".docx":
        return _parse_docx(path)
    raise ValueError(f"Định dạng tài liệu không được hỗ trợ: {suffix or '(không có)'}")


def _parse_pdf(path: Path) -> list[dict[str, int | None | str]]:
    chunks: list[dict[str, int | None | str]] = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text()
            if not page_text:
                continue
            # Cách chia chunk cho PDF:
            # File PDF lưu trữ ký tự theo tọa độ hình học (x, y) trên từng trang cố định,
            # không có cấu trúc đoạn văn ngữ nghĩa như file DOCX.
            # Do đó, ta tách theo từng dòng (splitlines) để tạo các chunk nhỏ gọn,
            # vừa giữ được số trang (page_number) chính xác để CitationVerifier định vị,
            # vừa tránh chunk quá dài làm giảm độ chính xác khi so khớp mờ (fuzzy match).
            for paragraph in page_text.splitlines():
                text = paragraph.strip()
                if text:
                    chunks.append(
                        {"chunk_id": len(chunks), "page": page_number, "text": text}
                    )
    if not chunks:
        raise ValueError(f"PDF không có lớp văn bản đọc được: {path.name}")
    return chunks


def _parse_docx(path: Path) -> list[dict[str, int | None | str]]:
    chunks: list[dict[str, int | None | str]] = []
    document = Document(path)
    # Cách chia chunk cho DOCX:
    # File DOCX sử dụng định dạng OpenXML bố cục dòng chảy (flow layout).
    # Khái niệm "trang" không tồn tại cố định trong file DOCX mà phụ thuộc vào
    # cỡ chữ, lề giấy và phần mềm hiển thị (Word/LibreOffice), do đó gán page = None.
    # Ngược lại, DOCX có cấu trúc đoạn (paragraph) rất rõ ràng trong XML,
    # nên ta lấy mỗi paragraph không rỗng làm một chunk độc lập theo đúng ngữ nghĩa.
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            chunks.append({"chunk_id": len(chunks), "page": None, "text": text})
    if not chunks:
        raise ValueError(f"DOCX không có đoạn văn bản đọc được: {path.name}")
    return chunks
