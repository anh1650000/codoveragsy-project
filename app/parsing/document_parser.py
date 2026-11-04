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
            # PDF thường không lưu ranh giới đoạn như DOCX; mỗi dòng trích được
            # là một đoạn gần đúng, nhỏ để giữ vị trí trang cho việc truy nguồn.
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
    # DOCX có các paragraph rõ ràng; mỗi đoạn là một chunk độc lập. Trang để
    # None vì phân trang phụ thuộc trình soạn thảo và không cố định trong DOCX.
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            chunks.append({"chunk_id": len(chunks), "page": None, "text": text})
    if not chunks:
        raise ValueError(f"DOCX không có đoạn văn bản đọc được: {path.name}")
    return chunks
