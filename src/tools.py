"""Tools for the agent."""
from typing import List, Dict, Any, Optional
from langchain.tools import tool
from langchain_core.messages import HumanMessage
from src.models import DocumentType, KnowledgeType
from src.rag_pipeline import HybridRetrieval, SemanticChunker
from src.knowledge_retrieval import KnowledgeRetrieval
from src.mock_api import MockAPI
from src.rollback import RollbackAPI, RollbackManager


# Initialize shared components
rag_pipeline = HybridRetrieval()
knowledge_retrieval = KnowledgeRetrieval()
chunker = SemanticChunker()
rollback_manager = RollbackManager()
rollback_api = RollbackAPI(rollback_manager)


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


@tool
def create_document(
    document_type: str,
    title: str,
    content: str,
    metadata: Optional[Dict[str, Any]] = None,
    api: Optional[MockAPI] = None
) -> Dict[str, Any]:
    """
    Create a new document.
    
    Args:
        document_type: Type of document (regulatory, clinical, etc.)
        title: Document title
        content: Document content
        metadata: Optional metadata
        api: Optional API instance (for evals, use MockAPI)
        
    Returns:
        Created document information with transaction ID
    """
    document_data = {
        "type": document_type,
        "title": title,
        "content": content,
        "metadata": metadata or {},
        "status": "draft"
    }
    
    # Use provided API or create a default one
    if api is None:
        api = MockAPI()
    
    def get_state(doc_id: str):
        return api.get_document(doc_id)
    
    def update_state(doc_id: str, data: Dict[str, Any]):
        return api.update_document(doc_id, data)
    
    def create_action():
        return api.create_document(document_data)
    
    result = rollback_api.execute_with_rollback(
        action_type="create",
        resource_id=document_data.get("id", "new"),
        resource_type="document",
        action_func=create_action,
        get_state_func=get_state,
        update_state_func=update_state
    )
    
    return result


@tool
def update_document(
    document_id: str,
    content: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    api: Optional[MockAPI] = None
) -> Dict[str, Any]:
    """
    Update an existing document.
    
    Args:
        document_id: Document ID
        content: Optional new content
        metadata: Optional metadata updates
        api: Optional API instance (for evals, use MockAPI)
        
    Returns:
        Update result with transaction ID
    """
    if api is None:
        api = MockAPI()
    
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
    
    result = rollback_api.execute_with_rollback(
        action_type="update",
        resource_id=document_id,
        resource_type="document",
        action_func=update_action,
        get_state_func=get_state,
        update_state_func=update_state
    )
    
    return result


@tool
def update_form_answer(
    form_id: str,
    question_id: str,
    answer: Any,
    api: Optional[MockAPI] = None
) -> Dict[str, Any]:
    """
    Update a form answer.
    
    Args:
        form_id: Form ID
        question_id: Question ID
        answer: Answer value
        api: Optional API instance (for evals, use MockAPI)
        
    Returns:
        Update result with transaction ID
    """
    if api is None:
        api = MockAPI()
    
    current_form = api.get_form(form_id)
    if "error" in current_form:
        return current_form
    
    def get_state(fid: str):
        return api.get_form(fid)
    
    def update_state(fid: str, data: Dict[str, Any]):
        return api.update_form_answer(fid, data.get("question_id"), data.get("answer"))
    
    def update_action():
        return api.update_form_answer(form_id, question_id, answer)
    
    result = rollback_api.execute_with_rollback(
        action_type="update",
        resource_id=form_id,
        resource_type="form",
        action_func=update_action,
        get_state_func=get_state,
        update_state_func=update_state
    )
    
    return result


@tool
def rollback_transaction(transaction_id: str) -> Dict[str, Any]:
    """
    Rollback a previous transaction.
    
    Args:
        transaction_id: Transaction ID to rollback
        
    Returns:
        Rollback result
    """
    return rollback_api.rollback_transaction(transaction_id)


# List of all tools
AGENT_TOOLS = [
    search_similar_devices,
    retrieve_knowledge,
    create_document,
    update_document,
    update_form_answer,
    rollback_transaction
]


