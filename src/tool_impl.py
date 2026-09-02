"""Shared implementation behind the agent's tools.

Both the LangChain-facing tools (src/tools.py, used by the LangGraph agent)
and the MCP-facing tools (src/mcp_server.py, used by external MCP clients)
are thin adapters over the functions in this module, so there is exactly one
implementation of each capability regardless of which interface calls it.

This module also owns the shared singletons (retrieval/knowledge clients,
rollback manager) and the mode-switching functions that point writes at
either the isolated eval store (MockAPI + InMemoryRollbackStorage) or the
durable production store (PostgresAPI + PostgresRollbackStorage). See ADR
E5 in Documentation/ARCHITECTURE_DECISIONS.md.
"""
from typing import Any, Dict, List, Optional

from src.rag_pipeline import HybridRetrieval, SemanticChunker
from src.knowledge_retrieval import KnowledgeRetrieval
from src.mock_api import MockAPI
from src.rollback import RollbackAPI, RollbackManager

# Shared components
rag_pipeline = HybridRetrieval()
knowledge_retrieval = KnowledgeRetrieval()
chunker = SemanticChunker()
rollback_manager = RollbackManager()
rollback_api = RollbackAPI(rollback_manager)

# The API that create/update/delete operations write to. Defaults to MockAPI
# (isolated, resettable) so importing this module never requires a database.
# configure_api() points it at PostgresAPI for production use.
_active_api: Any = MockAPI()


def configure_api(api: Any) -> None:
    """Set the API implementation the write tools should target."""
    global _active_api
    _active_api = api


def configure_rollback_manager(manager: RollbackManager) -> None:
    """Swap the rollback manager (and its dependent API) the write tools use."""
    global rollback_manager, rollback_api
    rollback_manager = manager
    rollback_api = RollbackAPI(rollback_manager)


def search_similar_devices_impl(device_description: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """Search for similar devices from FDA 510(k) documents."""
    results = rag_pipeline.retrieve(device_description, top_k=top_k)

    return [
        {
            "chunk_id": r.chunk_id,
            "content": r.content,
            "score": r.score,
            "document_id": r.document_id,
            "metadata": r.metadata
        }
        for r in results
    ]


def retrieve_knowledge_impl(
    query: str,
    client_id: Optional[str] = None,
    include_global: bool = True,
    include_client: bool = True,
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """Retrieve knowledge from global or client-specific stores."""
    chunks = knowledge_retrieval.retrieve(
        query=query,
        client_id=client_id,
        top_k=top_k,
        include_global=include_global,
        include_client=include_client
    )

    return [
        {
            "chunk_id": chunk.chunk_id,
            "content": chunk.content,
            "knowledge_type": chunk.knowledge_type.value,
            "source": chunk.source,
            "timestamp": chunk.timestamp.isoformat(),
            "confidence": chunk.confidence,
            "metadata": chunk.metadata
        }
        for chunk in chunks
    ]


def create_document_impl(
    document_type: str,
    title: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create a new document, tracked for rollback."""
    document_data = {
        "type": document_type,
        "title": title,
        "content": content,
        "metadata": metadata or {},
        "status": "draft"
    }

    api = _active_api

    def get_state(doc_id: str):
        return api.get_document(doc_id)

    def update_state(doc_id: str, data: Dict[str, Any]):
        return api.update_document(doc_id, data)

    def create_action():
        return api.create_document(document_data)

    return rollback_api.execute_with_rollback(
        action_type="create",
        resource_id=document_data.get("id", "new"),
        resource_type="document",
        action_func=create_action,
        get_state_func=get_state,
        update_state_func=update_state
    )


def update_document_impl(
    document_id: str,
    content: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Update an existing document, tracked for rollback."""
    api = _active_api

    current_doc = api.get_document(document_id)
    if "error" in current_doc:
        return current_doc

    def get_state(doc_id: str):
        return api.get_document(doc_id)

    def update_state(doc_id: str, data: Dict[str, Any]):
        return api.update_document(doc_id, data)

    def update_action():
        updates = {}
        if content:
            updates["content"] = content
        if metadata:
            updates["metadata"] = {**current_doc.get("metadata", {}), **metadata}
        return api.update_document(document_id, updates)

    return rollback_api.execute_with_rollback(
        action_type="update",
        resource_id=document_id,
        resource_type="document",
        action_func=update_action,
        get_state_func=get_state,
        update_state_func=update_state
    )


def update_form_answer_impl(form_id: str, question_id: str, answer: Any) -> Dict[str, Any]:
    """Update a form answer, tracked for rollback."""
    api = _active_api

    current_form = api.get_form(form_id)
    if "error" in current_form:
        return current_form

    def get_state(fid: str):
        return api.get_form(fid)

    def update_state(fid: str, data: Dict[str, Any]):
        return api.update_form_answer(fid, data.get("question_id"), data.get("answer"))

    def update_action():
        return api.update_form_answer(form_id, question_id, answer)

    return rollback_api.execute_with_rollback(
        action_type="update",
        resource_id=form_id,
        resource_type="form",
        action_func=update_action,
        get_state_func=get_state,
        update_state_func=update_state
    )


def rollback_transaction_impl(transaction_id: str) -> Dict[str, Any]:
    """Rollback a previous transaction."""
    return rollback_api.rollback_transaction(transaction_id)
