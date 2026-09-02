"""Basic usage examples for Medical Documentation Agents.

Referenced by Documentation/QUICKSTART.md and Documentation/SETUP.md. Each
function below is a standalone, runnable demonstration of one component;
run this file directly to try them in sequence, or import individual
functions to try one at a time.

Requires a configured .env (see .env.example) — at minimum OPENAI_API_KEY.
The RAG/knowledge examples also require a running Qdrant instance
(see Documentation/SETUP.md).
"""
from src.agent import MedicalDocumentationAgent
from src.rollback import RollbackManager, RollbackAPI
from src.rag_pipeline import HybridRetrieval
from src.knowledge_retrieval import KnowledgeRetrieval
from src.mock_api import MockAPI


def run_agent_example():
    """Run the full agent workflow in mock mode (safe — no Postgres required)."""
    agent = MedicalDocumentationAgent(use_mock_api=True)

    state = agent.run(
        task_description="Create regulatory documents for a blood glucose monitor",
        device_info={
            "name": "GlucoCheck Pro",
            "type": "Blood glucose monitor",
            "class": "Class II"
        },
        client_id="client_001"
    )

    print(f"Todos completed: {sum(1 for t in state.todos if t.status.value == 'completed')}/{len(state.todos)}")
    print(f"Documents created: {len(state.documents)}")
    return state


def rollback_example():
    """Execute a mock destructive action with rollback tracking, then undo it."""
    api = MockAPI()
    manager = RollbackManager()
    rollback_api = RollbackAPI(manager)

    result = rollback_api.execute_with_rollback(
        action_type="create",
        resource_id="doc_example",
        resource_type="document",
        action_func=lambda: api.create_document({"id": "doc_example", "title": "Example Doc", "content": "..."}),
        get_state_func=api.get_document,
        update_state_func=api.update_document
    )
    print(f"Created with transaction_id={result['transaction_id']}")

    undo_result = rollback_api.rollback_transaction(result["transaction_id"])
    print(f"Rolled back: {undo_result['success']}")
    return result


def rag_retrieval_example():
    """Query the hybrid (dense + sparse) retrieval pipeline for similar devices.

    Requires a running Qdrant instance and a populated 'device_documents'
    collection — returns an empty list against a fresh/empty index (see
    Documentation/ARCHITECTURE_DECISIONS.md, C3: no data ingestion pipeline
    exists yet).
    """
    rag = HybridRetrieval()
    results = rag.retrieve(
        query="blood glucose monitor",
        top_k=10,
        dense_weight=0.7,
        sparse_weight=0.3
    )
    print(f"Found {len(results)} similar device chunks")
    return results


def knowledge_retrieval_example():
    """Query global + client-specific knowledge stores.

    Requires a running Qdrant instance — returns an empty list against a
    fresh/empty index.
    """
    kr = KnowledgeRetrieval()
    chunks = kr.retrieve(
        query="clinical trial requirements",
        client_id="client_001",
        include_global=True,
        include_client=True
    )
    print(f"Found {len(chunks)} knowledge chunks")
    return chunks


if __name__ == "__main__":
    print("=== Rollback example (no external services required) ===")
    rollback_example()

    print("\n=== RAG retrieval example (requires Qdrant) ===")
    rag_retrieval_example()

    print("\n=== Knowledge retrieval example (requires Qdrant) ===")
    knowledge_retrieval_example()

    print("\n=== Full agent workflow (mock mode — requires OpenAI + Qdrant) ===")
    run_agent_example()
