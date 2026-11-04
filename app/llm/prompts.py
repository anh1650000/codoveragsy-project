"""Prompt trích xuất trường hợp đồng và trích dẫn nguyên văn."""

from collections.abc import Sequence


SYSTEM_PROMPT = """Bạn trích xuất thông tin từ hợp đồng tiếng Việt và chỉ trả về một JSON object hợp lệ.
Không thêm markdown hay nội dung bên ngoài JSON. JSON phải có đủ các khóa:
party_a_name, party_b_name, party_b_tax_code, party_b_legal_representative,
contract_value, effective_date, payment_terms. Mỗi khóa có object gồm value và quote.
Nếu tài liệu không có thông tin cho một trường, đặt cả value và quote thành null.
Giá trị phải được chép đúng như tài liệu, không tự chuẩn hóa. Quote phải chép nguyên văn
từ tài liệu; mỗi trường chỉ có một quote ngắn nhất có thể nhưng phải giữ nhãn đi cùng
giá trị (ví dụ: "Mã số thuế: 0312345678"). Không suy đoán hoặc bổ sung thông tin.
"""


def build_extraction_messages(
    chunks: Sequence[dict[str, int | None | str]],
    validation_error: str | None = None,
) -> list[dict[str, str]]:
    """Tạo hội thoại, có thể thêm lỗi validation để model sửa JSON ở lần thử sau."""
    document = "\n".join(
        f"[chunk_id={chunk['chunk_id']} page={chunk['page']}] {chunk['text']}"
        for chunk in chunks
    )
    user_prompt = f"Trích xuất các trường yêu cầu từ tài liệu sau:\n\n{document}"
    if validation_error:
        user_prompt += (
            "\n\nJSON trước đó sai cấu trúc. Hãy trả lại toàn bộ JSON đúng schema. "
            f"Lỗi validation: {validation_error}"
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
