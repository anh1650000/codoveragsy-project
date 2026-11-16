"""Động cơ đối soát thông tin Bên B với cơ sở dữ liệu master_entities bằng quy tắc thuần."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from rapidfuzz import fuzz

from app.core.config import get_setting
from app.extraction.schema import AuditItem, FieldStatus, VerifiedField
from app.guardrails.normalizers import (
    normalize_company_name,
    normalize_person_name,
    normalize_tax_code,
    parse_vnd,
)

DEFAULT_NAME_MATCH_THRESHOLD = 90.0
DEFAULT_NAME_SCORE_MARGIN = 5.0


class MasterEntityLike(Protocol):
    """Protocol đại diện cho bản ghi master_entities (hỗ trợ cả model SQLAlchemy lẫn mock object)."""

    vat_code: str
    company_name: str
    legal_representative: str | None
    max_contract_value: Decimal | None


class ReconciliationEngine:
    """Đối soát các trường đã được VERIFIED với danh sách master_entities, không gọi LLM."""

    def __init__(
        self,
        name_match_threshold: float | None = None,
        name_score_margin: float | None = None,
    ) -> None:
        self.name_match_threshold = (
            name_match_threshold
            if name_match_threshold is not None
            else float(get_setting("NAME_MATCH_THRESHOLD", str(DEFAULT_NAME_MATCH_THRESHOLD)))
        )
        self.name_score_margin = (
            name_score_margin
            if name_score_margin is not None
            else float(get_setting("NAME_SCORE_MARGIN", str(DEFAULT_NAME_SCORE_MARGIN)))
        )

    def reconcile(
        self,
        verified_fields: Sequence[VerifiedField],
        master_entities: Sequence[MasterEntityLike],
        existing_review_items: Sequence[AuditItem] = (),
    ) -> list[AuditItem]:
        """Thực hiện đối soát tổng thể và trả về danh sách các cảnh báo AuditItem.
        
        Quy tắc:
        - Chỉ dùng các trường có status == VERIFIED.
        - Tránh sinh trùng lặp lỗi NEEDS_HUMAN_REVIEW cho cùng một trường đã có trong existing_review_items.
        """
        field_map = {vf.name: vf for vf in verified_fields}
        existing_review_fields = {
            item.field_name
            for item in existing_review_items
            if item.error_type == "NEEDS_HUMAN_REVIEW" and item.field_name is not None
        }

        tax_field = field_map.get("party_b_tax_code")
        name_field = field_map.get("party_b_name")
        rep_field = field_map.get("party_b_legal_representative")
        val_field = field_map.get("contract_value")

        # Kiểm tra tính hợp lệ của giá trị số tiền nếu contract_value đã được verify
        value_audit_item = self._validate_contract_value_parseable(val_field, existing_review_fields)

        # Nhánh 1: MST đã được xác thực -> tìm theo MST trước
        if tax_field is not None and tax_field.status == FieldStatus.VERIFIED and tax_field.value:
            audit_items = self._reconcile_with_verified_tax_code(
                tax_field=tax_field,
                name_field=name_field,
                rep_field=rep_field,
                val_field=val_field,
                master_entities=master_entities,
                existing_review_fields=existing_review_fields,
            )
        else:
            # Nhánh 2: MST không được VERIFIED (hoặc thiếu) -> chỉ tìm kiếm theo tên
            audit_items = self._reconcile_without_verified_tax_code(
                name_field=name_field,
                rep_field=rep_field,
                val_field=val_field,
                master_entities=master_entities,
                existing_review_fields=existing_review_fields,
            )

        if value_audit_item is not None:
            audit_items.append(value_audit_item)

        return audit_items

    def _validate_contract_value_parseable(
        self,
        val_field: VerifiedField | None,
        existing_review_fields: set[str],
    ) -> AuditItem | None:
        """Kiểm tra giá trị hợp đồng có phân tích được thành số tiền không.
        
        VÌ SAO: Nếu trường contract_value có trích xuất nhưng parse_vnd trả về None,
        hệ thống không thể so sánh số học với hạn mức, buộc phải chuyển con người rà soát.
        """
        if (
            val_field is not None
            and val_field.status == FieldStatus.VERIFIED
            and val_field.value is not None
            and "contract_value" not in existing_review_fields
        ):
            parsed = parse_vnd(val_field.value)
            if parsed is None:
                return AuditItem(
                    error_type="NEEDS_HUMAN_REVIEW",
                    field_name="contract_value",
                    extracted_value=val_field.value,
                    expected_value=None,
                    detail=f"Giá trị hợp đồng '{val_field.value}' không thể phân tích thành số tiền hợp lệ để đối soát hạn mức.",
                )
        return None

    def _reconcile_with_verified_tax_code(
        self,
        tax_field: VerifiedField,
        name_field: VerifiedField | None,
        rep_field: VerifiedField | None,
        val_field: VerifiedField | None,
        master_entities: Sequence[MasterEntityLike],
        existing_review_fields: set[str],
    ) -> list[AuditItem]:
        """Xử lý đối soát khi MST Bên B đã được kiểm chứng trích dẫn thành công.
        
        VÌ SAO: MST là mã định danh duy nhất (khóa chính nghiệp vụ). Nếu tìm thấy theo MST,
        ta đối soát chéo tên, người đại diện và hạn mức với thực thể đó. Nếu không thấy theo MST,
        ta thử tìm theo tên để phân biệt giữa sai MST (IDENTITY_MISMATCH) và công ty mới hoàn toàn (ENTITY_NOT_FOUND).
        """
        assert tax_field.value is not None
        raw_tax = tax_field.value
        norm_tax = normalize_tax_code(raw_tax)

        entity_by_tax = next(
            (e for e in master_entities if normalize_tax_code(e.vat_code) == norm_tax),
            None,
        )

        if entity_by_tax is not None:
            # Tìm thấy đúng công ty theo MST: tiến hành kiểm tra thông tin chi tiết
            return self._verify_matched_entity_details(
                entity=entity_by_tax,
                name_field=name_field,
                rep_field=rep_field,
                val_field=val_field,
                existing_review_fields=existing_review_fields,
            )

        # Không tìm thấy theo MST: thử tìm theo tên để xem có phải gõ nhầm MST không
        return self._handle_tax_code_not_found(
            raw_tax=raw_tax,
            name_field=name_field,
            master_entities=master_entities,
            existing_review_fields=existing_review_fields,
        )

    def _verify_matched_entity_details(
        self,
        entity: MasterEntityLike,
        name_field: VerifiedField | None,
        rep_field: VerifiedField | None,
        val_field: VerifiedField | None,
        existing_review_fields: set[str],
    ) -> list[AuditItem]:
        """So khớp tên công ty, người đại diện và hạn mức giá trị với công ty đã tìm thấy.
        
        VÌ SAO: Dù đúng MST, hợp đồng vẫn có thể ghi sai tên pháp nhân, sai người đại diện ủy quyền
        hoặc giá trị hợp đồng vượt quá hạn mức rủi ro được phê duyệt cho đối tác này.
        """
        audit_items: list[AuditItem] = []

        # 1. So tên công ty bằng token_set_ratio sau khi chuẩn hóa viết tắt
        if name_field is not None and name_field.status == FieldStatus.VERIFIED and name_field.value:
            norm_extracted_name = normalize_company_name(name_field.value)
            norm_db_name = normalize_company_name(entity.company_name)
            name_score = fuzz.token_set_ratio(norm_extracted_name, norm_db_name)
            if name_score < self.name_match_threshold:
                audit_items.append(
                    AuditItem(
                        error_type="IDENTITY_MISMATCH",
                        field_name="party_b_name",
                        extracted_value=name_field.value,
                        expected_value=entity.company_name,
                        detail=(
                            f"Tên Bên B '{name_field.value}' không khớp với tên trong hệ thống '{entity.company_name}' "
                            f"(điểm khớp: {name_score:.1f}/{self.name_match_threshold})."
                        ),
                    )
                )

        # 2. So người đại diện pháp luật (nếu trích xuất được và đã verify)
        if rep_field is not None and rep_field.status == FieldStatus.VERIFIED and rep_field.value:
            if entity.legal_representative:
                norm_extracted_rep = normalize_person_name(rep_field.value)
                norm_db_rep = normalize_person_name(entity.legal_representative)
                rep_score = fuzz.token_set_ratio(norm_extracted_rep, norm_db_rep)
                if rep_score < self.name_match_threshold:
                    audit_items.append(
                        AuditItem(
                            error_type="IDENTITY_MISMATCH",
                            field_name="party_b_legal_representative",
                            extracted_value=rep_field.value,
                            expected_value=entity.legal_representative,
                            detail=(
                                f"Người đại diện '{rep_field.value}' không khớp với đại diện pháp luật trong hệ thống "
                                f"'{entity.legal_representative}' (điểm khớp: {rep_score:.1f}/{self.name_match_threshold})."
                            ),
                        )
                    )

        # 3. So hạn mức giá trị hợp đồng
        if val_field is not None and val_field.status == FieldStatus.VERIFIED and val_field.value:
            parsed_val = parse_vnd(val_field.value)
            if parsed_val is not None and entity.max_contract_value is not None:
                if parsed_val > entity.max_contract_value:
                    audit_items.append(
                        AuditItem(
                            error_type="VALUE_OVER_LIMIT",
                            field_name="contract_value",
                            extracted_value=str(parsed_val),
                            expected_value=str(entity.max_contract_value),
                            detail=(
                                f"Giá trị hợp đồng ({parsed_val:,.0f} VND) vượt quá hạn mức tối đa của đối tác "
                                f"({entity.max_contract_value:,.0f} VND)."
                            ),
                        )
                    )

        return audit_items

    def _handle_tax_code_not_found(
        self,
        raw_tax: str,
        name_field: VerifiedField | None,
        master_entities: Sequence[MasterEntityLike],
        existing_review_fields: set[str],
    ) -> list[AuditItem]:
        """Xử lý trường hợp MST không tồn tại trong hệ thống.
        
        VÌ SAO: Nếu không tìm thấy MST, ta thử so khớp theo tên công ty. Nếu tên khớp một đối tác
        trong hệ thống thì hợp đồng bị ghi sai MST (IDENTITY_MISMATCH). Nếu tên cũng không khớp ai,
        đối tác này hoàn toàn chưa có trong hồ sơ công ty (ENTITY_NOT_FOUND).
        """
        if name_field is not None and name_field.status == FieldStatus.VERIFIED and name_field.value:
            matched, is_ambiguous, ambiguity_msg = self._find_candidates_by_name(
                name_field.value, master_entities
            )
            if is_ambiguous:
                if "party_b_name" not in existing_review_fields:
                    return [
                        AuditItem(
                            error_type="NEEDS_HUMAN_REVIEW",
                            field_name="party_b_name",
                            extracted_value=name_field.value,
                            expected_value=None,
                            detail=ambiguity_msg,
                        )
                    ]
                return []

            if matched is not None:
                return [
                    AuditItem(
                        error_type="IDENTITY_MISMATCH",
                        field_name="party_b_tax_code",
                        extracted_value=raw_tax,
                        expected_value=matched.vat_code,
                        detail=(
                            f"MST trong hợp đồng '{raw_tax}' không khớp với MST '{matched.vat_code}' "
                            f"của công ty '{matched.company_name}' trong hệ thống."
                        ),
                    )
                ]

        # Cả MST và tên đều không khớp bất kỳ đơn vị nào trong hệ thống
        return [
            AuditItem(
                error_type="ENTITY_NOT_FOUND",
                field_name="party_b_tax_code",
                extracted_value=raw_tax,
                expected_value=None,
                detail=f"Không tìm thấy đối tác với MST '{raw_tax}' hoặc tên tương ứng trong hệ thống master_entities.",
            )
        ]

    def _reconcile_without_verified_tax_code(
        self,
        name_field: VerifiedField | None,
        rep_field: VerifiedField | None,
        val_field: VerifiedField | None,
        master_entities: Sequence[MasterEntityLike],
        existing_review_fields: set[str],
    ) -> list[AuditItem]:
        """Xử lý đối soát khi MST Bên B bị thiếu hoặc không đạt kiểm chứng trích dẫn.
        
        VÌ SAO: Khi không có MST đáng tin cậy, ta chỉ có thể thử nhận diện đối tác qua tên.
        Nếu tìm thấy duy nhất 1 công ty khớp tên, ta tiếp tục kiểm tra người đại diện và hạn mức.
        Nếu không tìm thấy ai, tuyệt đối KHÔNG vội kết luận là ENTITY_NOT_FOUND mà phải chuyển
        con người kiểm tra (NEEDS_HUMAN_REVIEW) vì trích xuất ban đầu đã thiếu sót.
        """
        if name_field is None or name_field.status != FieldStatus.VERIFIED or not name_field.value:
            # Cả tên và MST đều không có field VERIFIED; collect_review_items đã gom NEEDS_HUMAN_REVIEW
            return []

        matched, is_ambiguous, ambiguity_msg = self._find_candidates_by_name(
            name_field.value, master_entities
        )

        if is_ambiguous:
            if "party_b_name" not in existing_review_fields:
                return [
                    AuditItem(
                        error_type="NEEDS_HUMAN_REVIEW",
                        field_name="party_b_name",
                        extracted_value=name_field.value,
                        expected_value=None,
                        detail=ambiguity_msg,
                    )
                ]
            return []

        if matched is None:
            # Không tìm thấy công ty theo tên và MST không được verify -> NEEDS_HUMAN_REVIEW
            if "party_b_name" not in existing_review_fields and "party_b_tax_code" not in existing_review_fields:
                return [
                    AuditItem(
                        error_type="NEEDS_HUMAN_REVIEW",
                        field_name="party_b_name",
                        extracted_value=name_field.value,
                        expected_value=None,
                        detail=(
                            f"MST Bên B không được xác thực và tên '{name_field.value}' không khớp với đối tác nào "
                            "trong hệ thống, cần người kiểm tra thủ công."
                        ),
                    )
                ]
            return []

        # Khớp được duy nhất 1 công ty theo tên: kiểm tra tiếp người đại diện và hạn mức
        return self._verify_matched_entity_details(
            entity=matched,
            name_field=name_field,
            rep_field=rep_field,
            val_field=val_field,
            existing_review_fields=existing_review_fields,
        )

    def _find_candidates_by_name(
        self,
        extracted_name: str,
        master_entities: Sequence[MasterEntityLike],
    ) -> tuple[MasterEntityLike | None, bool, str]:
        """Tìm kiếm công ty theo tên mờ, xử lý trường hợp có nhiều ứng viên sát điểm nhau.
        
        Trả về: (ứng viên tốt nhất, cờ mơ hồ, thông điệp chi tiết).
        VÌ SAO: Nếu hai công ty khác nhau có tên rút gọn tương tự nhau và điểm so khớp chênh lệch
        nhỏ hơn NAME_SCORE_MARGIN (mặc định 5.0), thuật toán không được tự ý quyết định mà phải
        đánh dấu mơ hồ để con người can thiệp.
        """
        norm_target = normalize_company_name(extracted_name)
        scored_candidates: list[tuple[float, MasterEntityLike]] = []

        for entity in master_entities:
            norm_db = normalize_company_name(entity.company_name)
            score = float(fuzz.token_set_ratio(norm_target, norm_db))
            if score >= self.name_match_threshold:
                scored_candidates.append((score, entity))

        if not scored_candidates:
            return None, False, ""

        # Sắp xếp điểm giảm dần
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        top1_score, top1_entity = scored_candidates[0]

        if len(scored_candidates) >= 2:
            top2_score, top2_entity = scored_candidates[1]
            diff = top1_score - top2_score
            if diff <= self.name_score_margin:
                msg = (
                    f"Có nhiều ứng viên đạt ngưỡng ({self.name_match_threshold}) với điểm sát nhau "
                    f"(chênh lệch {diff:.1f} <= {self.name_score_margin}): "
                    f"'{top1_entity.company_name}' ({top1_score:.1f}) và "
                    f"'{top2_entity.company_name}' ({top2_score:.1f}). Cần kiểm tra thủ công."
                )
                return None, True, msg

        return top1_entity, False, ""
