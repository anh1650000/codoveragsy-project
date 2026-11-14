"""Prompt trích xuất trường hợp đồng và trích dẫn nguyên văn."""

from collections.abc import Sequence

from app.extraction.schema import FieldStatus, VerifiedField


SYSTEM_PROMPT = """Bạn là trợ lý AI chuyên trích xuất thông tin hợp đồng kinh tế tiếng Việt.
Nhiệm vụ của bạn là đọc kỹ văn bản và chỉ trả về DUY NHẤT một JSON object hợp lệ, không có markdown (không dùng ```json) và không kèm lời giải thích nào khác.

JSON phải chứa đầy đủ 7 trường sau:
1. party_a_name: Tên đơn vị Bên A (thường đi sau nhãn "BÊN A:").
2. party_b_name: Tên đơn vị Bên B (thường đi sau nhãn "BÊN B:").
3. party_b_tax_code: Mã số thuế của Bên B (thường nằm ngay dưới phần Bên B, ví dụ nhãn "Mã số thuế: ...").
4. party_b_legal_representative: Người đại diện của Bên B (thường nằm dưới phần Bên B, ví dụ nhãn "Người đại diện: ...").
5. contract_value: Giá trị hợp đồng (ví dụ đi sau nhãn "Giá trị hợp đồng: ...").
6. effective_date: Ngày lập, ngày ký hoặc ngày hiệu lực (thường ở câu đầu hợp đồng, ví dụ: "Hôm nay, ngày...").
7. payment_terms: Điều khoản hoặc thời hạn thanh toán (câu quy định việc thanh toán, ví dụ có chữ "thanh toán").

Mỗi trường là một object gồm hai khóa:
- "value": Giá trị trích xuất được, chép đúng nguyên văn từ tài liệu, không tự ý chuẩn hóa hay đổi định dạng.
- "quote": Đoạn văn nguyên văn trích từ tài liệu chứa giá trị trên; mỗi trường chỉ dùng một quote ngắn nhất có thể nhưng phải giữ nguyên nhãn đi cùng giá trị (ví dụ: "Mã số thuế: 0312345678", "Người đại diện: Nguyễn Văn A").

Quy tắc bắt buộc:
- Nếu tài liệu hoàn toàn KHÔNG có thông tin cho một trường, bắt buộc trả về: {"value": null, "quote": null}. Tuyệt đối không được bịa ra thông tin.
- Không suy đoán hoặc bổ sung dữ liệu không có trong hợp đồng.
"""


def build_extraction_messages(
    chunks: Sequence[dict[str, int | None | str]],
    validation_error: str | None = None,
) -> list[dict[str, str]]:
    """Tạo hội thoại prompt trích xuất cho mô hình LLM."""
    document = "\n".join(str(chunk["text"]) for chunk in chunks)
    user_prompt = f"Văn bản hợp đồng:\n---\n{document}\n---\n\nHãy trích xuất đúng 7 trường yêu cầu thành JSON:"
    if validation_error:
        user_prompt += (
            f"\n\nLƯU Ý: Lần gọi trước bị lỗi cấu trúc JSON hoặc schema: {validation_error}\n"
            "Hãy sửa lỗi và trả lời lại bằng một JSON object hợp lệ đầy đủ 7 trường."
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


RETRY_SYSTEM_PROMPT = """Bạn là trợ lý AI chuyên sửa lỗi trích xuất thông tin hợp đồng kinh tế tiếng Việt.
Chỉ trả về DUY NHẤT một JSON object hợp lệ (không markdown, không giải thích) chứa ĐÚNG các trường bị lỗi được liệt kê.

Mỗi trường là một object gồm hai khóa:
- "value": Giá trị chép đúng nguyên văn từ tài liệu, không tự ý đổi định dạng.
- "quote": Câu/đoạn nguyên văn ngắn nhất có mặt trong tài liệu chứa giá trị trên (kèm nhãn đi cùng nếu có).

Quy tắc bắt buộc:
- Tuyệt đối KHÔNG tự bịa quote hoặc sửa chữ trong tài liệu.
- Nếu tài liệu KHÔNG có thông tin cho trường đó, bắt buộc trả về: {"value": null, "quote": null}.
"""


def _describe_retry_reason(field: VerifiedField) -> str:
    """Chuyển trạng thái lỗi của verifier thành lời nhắc rõ ràng cho LLM."""
    if field.status == FieldStatus.QUOTE_NOT_FOUND:
        return "quote bạn đưa không xuất hiện trong tài liệu"
    if field.status == FieldStatus.VALUE_NOT_IN_QUOTE:
        return "giá trị không nằm trong quote"
    return f"không đạt kiểm chứng ({field.status.value})"


def build_retry_extraction_messages(
    chunks: Sequence[dict[str, int | None | str]],
    failed_fields: Sequence[VerifiedField],
    validation_error: str | None = None,
) -> list[dict[str, str]]:
    """Tạo prompt retry chỉ yêu cầu lại các trường lỗi kèm nguyên nhân kiểm chứng."""
    document = "\n".join(str(chunk["text"]) for chunk in chunks)
    error_lines = "\n".join(
        f"- {field.name}: {_describe_retry_reason(field)} "
        f"(lần trước value={field.value!r}, quote={field.quote!r})"
        for field in failed_fields
    )
    field_list = ", ".join(field.name for field in failed_fields)
    user_prompt = (
        f"Văn bản hợp đồng:\n---\n{document}\n---\n\n"
        f"Các trường sau kiểm chứng thất bại ở lần trước:\n{error_lines}\n\n"
        f"Hãy trích xuất lại CHỈ các trường [{field_list}] thành JSON object. "
        "Nếu tài liệu thực sự không có thông tin, trả về {\"value\": null, \"quote\": null}."
    )
    if validation_error:
        user_prompt += (
            f"\n\nLƯU Ý: Lần gọi trước bị lỗi cấu trúc JSON hoặc schema: {validation_error}\n"
            f"Hãy sửa lỗi và trả về JSON object hợp lệ chứa đủ các khóa: {field_list}."
        )
    return [
        {"role": "system", "content": RETRY_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
