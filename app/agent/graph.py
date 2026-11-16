"""Lắp ráp LangGraph StateGraph cho quy trình thẩm định hợp đồng."""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    FAILED_VERIFY_STATUSES,
    AgentConfig,
    ExtractorFn,
    MasterEntitiesProviderFn,
    ParserFn,
    RetryExtractorFn,
    VerifierFn,
    build_nodes,
)
from app.agent.state import ContractAuditState
from app.reconciliation.engine import MasterEntityLike, ReconciliationEngine


def make_initial_state(file_path: str | Path, contract_id: int = 0) -> ContractAuditState:
    """Tạo state khởi đầu chuẩn cho một lần chạy graph."""
    return {
        "contract_id": contract_id,
        "file_path": str(file_path),
        "chunks": [],
        "raw_extraction": None,
        "verified_fields": [],
        "retry_count": 0,
        "audit_items": [],
        "overall_result": None,
        "report": None,
        "trace_log": [],
    }


def build_contract_audit_graph(
    *,
    parser: ParserFn | None = None,
    extractor: ExtractorFn | None = None,
    retry_extractor: RetryExtractorFn | None = None,
    verifier: VerifierFn | None = None,
    reconciliation_engine: ReconciliationEngine | None = None,
    master_entities: Sequence[MasterEntityLike] | None = None,
    master_entities_provider: MasterEntitiesProviderFn | None = None,
    config: AgentConfig | None = None,
):
    """Dựng và compile StateGraph đúng luồng và luật rẽ nhánh ở mục 7 của AGENTS.md."""
    cfg = config or AgentConfig.from_env()
    nodes = build_nodes(
        parser=parser,
        extractor=extractor,
        retry_extractor=retry_extractor,
        verifier=verifier,
        reconciliation_engine=reconciliation_engine,
        master_entities=master_entities,
        master_entities_provider=master_entities_provider,
        config=cfg,
    )

    def route_after_verify(state: ContractAuditState) -> Literal["retry", "reconcile"]:
        """Quyết định thử lại field lỗi hay đi tiếp sang đối soát để tránh lặp vô hạn."""
        if not cfg.enable_verifier or not cfg.enable_retry:
            return "reconcile"
        if state.get("retry_count", 0) >= cfg.max_retries:
            return "reconcile"
        has_failed = any(
            vf.status in FAILED_VERIFY_STATUSES
            for vf in state.get("verified_fields", [])
        )
        return "retry" if has_failed else "reconcile"

    builder = StateGraph(ContractAuditState)
    for node_name, node_fn in nodes.items():
        builder.add_node(node_name, node_fn)

    builder.add_edge(START, "parse_node")
    builder.add_edge("parse_node", "extract_node")
    builder.add_edge("extract_node", "verify_citation_node")
    builder.add_conditional_edges(
        "verify_citation_node",
        route_after_verify,
        {
            "retry": "retry_extraction_node",
            "reconcile": "reconcile_db_node",
        },
    )
    builder.add_edge("retry_extraction_node", "verify_citation_node")
    builder.add_edge("reconcile_db_node", "generate_report_node")
    builder.add_edge("generate_report_node", END)

    return builder.compile()
