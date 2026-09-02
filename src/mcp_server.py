"""stdio MCP server exposing the agent's tools to external MCP clients.

Wraps the same functions used by the LangGraph agent (src/tool_impl.py, also
adapted for LangChain in src/tools.py) so there is one implementation of each
capability regardless of which interface calls it. See ADR B4 in
Documentation/ARCHITECTURE_DECISIONS.md for the design discussion.

This server is started independently of MedicalDocumentationAgent (e.g. by
Claude Desktop), so there is no agent wiring it to a storage mode. It reads
MCP_SERVER_MODE at startup instead:

- "eval" (default): MockAPI + InMemoryRollbackStorage — isolated, resettable.
  Safe default: this server has no authentication layer, and ADR entries I1/I3
  (secrets management, multi-tenancy enforcement) are still open, so writes
  should not reach durable production storage unless explicitly opted into.
- "production": PostgresAPI + PostgresRollbackStorage — durable, explicit opt-in.

Run with: python -m src.mcp_server
"""
import os
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from src import tool_impl

mcp_app = FastMCP("medical-documentation-agents")


def _configure_storage_mode() -> None:
    mode = os.getenv("MCP_SERVER_MODE", "eval").lower()

    if mode == "production":
        from src.postgres_api import PostgresAPI
        from src.rollback import PostgresRollbackStorage

        tool_impl.configure_api(PostgresAPI())
        tool_impl.configure_rollback_manager(tool_impl.RollbackManager(PostgresRollbackStorage()))
    elif mode == "eval":
        pass  # tool_impl already defaults to MockAPI + InMemoryRollbackStorage
    else:
        raise ValueError(f"Unknown MCP_SERVER_MODE: {mode!r} (expected 'eval' or 'production')")


@mcp_app.tool()
def search_similar_devices(device_description: str, top_k: int = 10) -> List[Dict[str, Any]]:
    """Search for similar devices from FDA 510(k) documents."""
    return tool_impl.search_similar_devices_impl(device_description, top_k=top_k)


@mcp_app.tool()
def retrieve_knowledge(
    query: str,
    client_id: Optional[str] = None,
    include_global: bool = True,
    include_client: bool = True,
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """Retrieve knowledge from global or client-specific stores."""
    return tool_impl.retrieve_knowledge_impl(
        query,
        client_id=client_id,
        include_global=include_global,
        include_client=include_client,
        top_k=top_k
    )


@mcp_app.tool()
def create_document(
    document_type: str,
    title: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create a new document."""
    return tool_impl.create_document_impl(document_type, title, content, metadata=metadata)


@mcp_app.tool()
def update_document(
    document_id: str,
    content: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Update an existing document."""
    return tool_impl.update_document_impl(document_id, content=content, metadata=metadata)


@mcp_app.tool()
def update_form_answer(form_id: str, question_id: str, answer: Any) -> Dict[str, Any]:
    """Update a form answer."""
    return tool_impl.update_form_answer_impl(form_id, question_id, answer)


@mcp_app.tool()
def rollback_transaction(transaction_id: str) -> Dict[str, Any]:
    """Rollback a previous transaction."""
    return tool_impl.rollback_transaction_impl(transaction_id)


if __name__ == "__main__":
    _configure_storage_mode()
    mcp_app.run(transport="stdio")
