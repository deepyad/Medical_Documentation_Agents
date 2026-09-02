"""LangChain tool adapters for the agent.

Thin wrappers over the shared logic in src/tool_impl.py — see that module for
the actual implementations, shared singletons, and configure_api()/
configure_rollback_manager() used to switch between eval and production
storage. src/mcp_server.py wraps the same tool_impl functions for MCP clients.
"""
from typing import List, Dict, Any, Optional
from langchain.tools import tool

from src import tool_impl


@tool
def search_similar_devices(
    device_description: str,
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """
    Search for similar devices from FDA 510(k) documents.

    Args:
        device_description: Description of the device to find similar ones for
        top_k: Number of similar devices to return

    Returns:
        List of similar device documents
    """
    return tool_impl.search_similar_devices_impl(device_description, top_k=top_k)


@tool
def retrieve_knowledge(
    query: str,
    client_id: Optional[str] = None,
    include_global: bool = True,
    include_client: bool = True,
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """
    Retrieve knowledge from global or client-specific stores.

    Args:
        query: Query string
        client_id: Optional client ID for client-specific knowledge
        include_global: Include global knowledge
        include_client: Include client-specific knowledge
        top_k: Number of results to return

    Returns:
        List of knowledge chunks
    """
    return tool_impl.retrieve_knowledge_impl(
        query,
        client_id=client_id,
        include_global=include_global,
        include_client=include_client,
        top_k=top_k
    )


@tool
def create_document(
    document_type: str,
    title: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a new document.

    Args:
        document_type: Type of document (regulatory, clinical, etc.)
        title: Document title
        content: Document content
        metadata: Optional metadata

    Returns:
        Created document information with transaction ID
    """
    return tool_impl.create_document_impl(document_type, title, content, metadata=metadata)


@tool
def update_document(
    document_id: str,
    content: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Update an existing document.

    Args:
        document_id: Document ID
        content: Optional new content
        metadata: Optional metadata updates

    Returns:
        Update result with transaction ID
    """
    return tool_impl.update_document_impl(document_id, content=content, metadata=metadata)


@tool
def update_form_answer(
    form_id: str,
    question_id: str,
    answer: Any
) -> Dict[str, Any]:
    """
    Update a form answer.

    Args:
        form_id: Form ID
        question_id: Question ID
        answer: Answer value

    Returns:
        Update result with transaction ID
    """
    return tool_impl.update_form_answer_impl(form_id, question_id, answer)


@tool
def rollback_transaction(transaction_id: str) -> Dict[str, Any]:
    """
    Rollback a previous transaction.

    Args:
        transaction_id: Transaction ID to rollback

    Returns:
        Rollback result
    """
    return tool_impl.rollback_transaction_impl(transaction_id)


# List of all tools
AGENT_TOOLS = [
    search_similar_devices,
    retrieve_knowledge,
    create_document,
    update_document,
    update_form_answer,
    rollback_transaction
]
