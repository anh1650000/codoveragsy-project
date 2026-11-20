"""Lớp truy xuất và thao tác dữ liệu (Repository) cho cơ sở dữ liệu PostgreSQL."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AuditLog, Contract, ContractEntity, MasterEntity


def _utc_now_naive() -> datetime:
    """Trả về thời gian UTC dạng naive để khớp cột TIMESTAMP WITHOUT TIME ZONE trong PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ContractRepository:
    """Các thao tác bất đồng bộ trên các bảng contracts, contract_entities và audit_logs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_contract(self, file_name: str, file_path: str) -> Contract:
        """Tạo mới một bản ghi hợp đồng với trạng thái UPLOADED."""
        contract = Contract(
            file_name=file_name,
            file_path=file_path,
            status="UPLOADED",
            created_at=_utc_now_naive(),
        )
        self.session.add(contract)
        await self.session.commit()
        await self.session.refresh(contract)
        return contract

    async def get_contract(self, contract_id: int) -> Contract | None:
        """Lấy thông tin hợp đồng theo ID."""
        stmt = select(Contract).where(Contract.id == contract_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_contract_with_details(self, contract_id: int) -> dict[str, Any] | None:
        """Lấy thông tin hợp đồng cùng danh sách fields và audit_logs để trả về API."""
        stmt = (
            select(Contract)
            .where(Contract.id == contract_id)
            .options(
                selectinload(Contract.entities),
                selectinload(Contract.audit_logs),
            )
        )
        result = await self.session.execute(stmt)
        contract = result.scalar_one_or_none()
        if contract is None:
            return None

        # Trích xuất danh sách fields và retry_count từ ContractEntity gần nhất
        latest_entity = contract.entities[-1] if contract.entities else None
        fields_data = latest_entity.fields if latest_entity else []
        retry_count = latest_entity.retry_count if latest_entity else 0

        # Trích xuất danh sách audit items
        audit_items_data = [
            {
                "error_type": log.error_type,
                "field_name": log.field_name,
                "extracted_value": log.extracted_value,
                "expected_value": log.expected_value,
                "detail": log.detail,
            }
            for log in contract.audit_logs
        ]

        return {
            "contract_id": contract.id,
            "file_name": contract.file_name,
            "status": contract.status,
            "overall_result": contract.overall_result,
            "error_message": contract.error_message,
            "fields": fields_data,
            "audit_items": audit_items_data,
            "retry_count": retry_count,
            "trace_log": contract.trace_log,
            "created_at": contract.created_at.isoformat() if contract.created_at else None,
            "completed_at": contract.completed_at.isoformat() if contract.completed_at else None,
        }

    async def update_status(
        self,
        contract_id: int,
        status: str,
        error_message: str | None = None,
    ) -> Contract | None:
        """Cập nhật trạng thái xử lý của hợp đồng."""
        contract = await self.get_contract(contract_id)
        if contract is None:
            return None
        contract.status = status
        if error_message is not None:
            contract.error_message = error_message
        if status in {"DONE", "FAILED"}:
            contract.completed_at = _utc_now_naive()
        await self.session.commit()
        await self.session.refresh(contract)
        return contract

    async def reset_for_reprocess(self, contract_id: int) -> Contract | None:
        """Dọn dẹp kết quả cũ và chuyển hợp đồng về PROCESSING để thẩm định lại."""
        contract = await self.get_contract(contract_id)
        if contract is None:
            return None

        # Xóa các thực thể và log kiểm toán cũ liên quan tới contract này
        await self.session.execute(
            delete(ContractEntity).where(ContractEntity.contract_id == contract_id)
        )
        await self.session.execute(
            delete(AuditLog).where(AuditLog.contract_id == contract_id)
        )

        contract.status = "PROCESSING"
        contract.overall_result = None
        contract.error_message = None
        contract.completed_at = None
        contract.trace_log = None
        await self.session.commit()
        await self.session.refresh(contract)
        return contract

    async def save_audit_results(
        self,
        contract_id: int,
        overall_result: str,
        verified_fields: list[dict[str, Any]],
        audit_items: list[dict[str, Any]],
        retry_count: int,
        trace_log: list[dict[str, Any]],
        error_message: str | None = None,
    ) -> Contract | None:
        """Lưu toàn bộ kết quả thẩm định vào contracts, contract_entities và audit_logs."""
        contract = await self.get_contract(contract_id)
        if contract is None:
            return None

        # 1. Lưu thông tin các trường trích xuất và trạng thái vào contract_entities
        contract_entity = ContractEntity(
            contract_id=contract_id,
            fields=verified_fields,
            retry_count=retry_count,
            created_at=_utc_now_naive(),
        )
        self.session.add(contract_entity)

        # 2. Lưu từng cảnh báo vào bảng audit_logs
        for item in audit_items:
            audit_log = AuditLog(
                contract_id=contract_id,
                error_type=item.get("error_type", "NEEDS_HUMAN_REVIEW"),
                field_name=item.get("field_name"),
                extracted_value=item.get("extracted_value"),
                expected_value=item.get("expected_value"),
                detail=item.get("detail"),
                created_at=_utc_now_naive(),
            )
            self.session.add(audit_log)

        # 3. Cập nhật bảng contracts
        contract.status = "DONE" if error_message is None else "FAILED"
        contract.overall_result = overall_result
        contract.error_message = error_message
        contract.trace_log = trace_log
        contract.completed_at = _utc_now_naive()

        await self.session.commit()
        await self.session.refresh(contract)
        return contract

    async def get_all_master_entities(self) -> list[MasterEntity]:
        """Lấy toàn bộ danh mục đối tác chuẩn từ master_entities để đối soát."""
        stmt = select(MasterEntity)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_master_entity_by_vat(self, vat_code: str) -> MasterEntity | None:
        """Tra cứu đối tác theo mã số thuế chuẩn."""
        stmt = select(MasterEntity).where(MasterEntity.vat_code == vat_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
