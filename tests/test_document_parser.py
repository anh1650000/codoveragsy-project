from pathlib import Path

import pytest

from app.parsing.document_parser import parse_document


ROOT = Path(__file__).resolve().parents[1]


def test_parse_pdf_returns_ordered_page_chunks_with_vietnamese_text():
    chunks = parse_document(ROOT / "data" / "contracts" / "hd_001.pdf")

    assert chunks
    assert [chunk["chunk_id"] for chunk in chunks] == list(range(len(chunks)))
    assert all(isinstance(chunk["page"], int) and chunk["page"] >= 1 for chunk in chunks)
    assert all(chunk["text"].strip() for chunk in chunks)
    assert any("An Phát" in chunk["text"] for chunk in chunks)


def test_parse_docx_uses_paragraphs_and_has_no_page_number():
    chunks = parse_document(ROOT / "data" / "contracts" / "hd_002.docx")

    assert chunks
    assert [chunk["chunk_id"] for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk["page"] is None for chunk in chunks)
    assert all(chunk["text"].strip() for chunk in chunks)
    assert any("Bình Minh" in chunk["text"] for chunk in chunks)


def test_parse_document_rejects_unsupported_extension(tmp_path):
    unsupported = tmp_path / "contract.txt"
    unsupported.write_text("text", encoding="utf-8")

    with pytest.raises(ValueError, match="không được hỗ trợ"):
        parse_document(unsupported)


def test_parse_document_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        parse_document(ROOT / "data" / "contracts" / "non_existent_file.pdf")


def test_parse_empty_docx_raises_value_error(tmp_path):
    from docx import Document

    empty_docx = tmp_path / "empty.docx"
    doc = Document()
    doc.save(empty_docx)

    with pytest.raises(ValueError, match="không có đoạn văn bản đọc được"):
        parse_document(empty_docx)

