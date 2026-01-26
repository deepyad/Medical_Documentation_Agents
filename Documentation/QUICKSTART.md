# Quick Start Guide

## Prerequisites

1. Python 3.9+
2. OpenAI API key
3. LangSmith API key (for evaluations)
4. Qdrant (can use local instance or cloud)

## Installation

```bash
# Clone or navigate to project directory
cd Medical_Documentation_Agents

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and add your API keys
```

## Quick Start - Running the Agent

### 1. Basic Agent Run

```python
from src.agent import MedicalDocumentationAgent

agent = MedicalDocumentationAgent(use_mock_api=True)  # Use mock API for safe testing

state = agent.run(
    task_description="Create regulatory documents for a blood glucose monitor",
    device_info={
        "name": "GlucoCheck Pro",
        "type": "Blood glucose monitor",
        "class": "Class II"
    },
    client_id="client_001"
)
```

This mirrors the sample scenario baked into `run_agent.py`. You can adapt it by passing different task/device payloads or by adding CLI arguments inside the script.

### 2. Run with Script

```bash
python run_agent.py
```

`run_agent.py` requires no additional inputs—it ships with the same task and device payload shown above and runs in production mode (`use_mock_api=False`). Edit the script if you want to exercise other scenarios.

## Quick Start - Running Evaluations

### 1. Set Up LangSmith

```bash
# Set your LangSmith API key in .env
LANGCHAIN_API_KEY=your_key_here
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=medical-documentation-agents
```

### 2. Run Evaluations

```bash
python run_evals.py
```

`run_evals.py` invokes the LangSmith-backed evaluation flow in mock mode using your configured scenarios—no manual input required once env vars are set.

Or programmatically:

```python
from src.evals import AgentEvaluator

evaluator = AgentEvaluator()
results = evaluator.run_evaluation()
```

See `Documentation/EVALUATION_LAYER.md` for a detailed walkthrough of the evaluation pipeline.

## Key Components

### Rollback System

```python
from src.rollback import RollbackManager, RollbackAPI

manager = RollbackManager()
api = RollbackAPI(manager)

# Execute action with rollback
result = api.execute_with_rollback(...)

# Rollback if needed
api.rollback_transaction(result["transaction_id"])
```

### RAG Pipeline

```python
from src.rag_pipeline import HybridRetrieval

rag = HybridRetrieval()
results = rag.retrieve(
    query="blood glucose monitor",
    top_k=10,
    dense_weight=0.7,
    sparse_weight=0.3
)
```

### Knowledge Retrieval

```python
from src.knowledge_retrieval import KnowledgeRetrieval

kr = KnowledgeRetrieval()
chunks = kr.retrieve(
    query="clinical trial requirements",
    client_id="client_001",
    include_global=True,
    include_client=True
)
```

### Mock API for Evals

```python
from src.mock_api import MockAPI

# Create with snapshot data
mock_api = MockAPI(snapshot_data={...})

# Use in agent
agent = MedicalDocumentationAgent(use_mock_api=True)
agent.mock_api = mock_api

# Reset after eval
mock_api.reset_database()
```

Refer to `Documentation/KNOWLEDGE_LAYER.md` and `Documentation/EVALUATION_LAYER.md` for architecture deep dives on these components.

## Configuration

Key settings in `src/config.py`:

- `context_window_limit`: Token limit before compression (default: 8000)
- `context_compression_threshold`: Compression threshold (default: 0.6)
- `chunk_size`: Document chunk size (default: 400)
- `top_k_retrieval`: Number of results to retrieve (default: 10)

## Troubleshooting

### Qdrant Connection Issues

If Qdrant is not running locally:

```bash
# Start Qdrant with Docker
docker run -p 6333:6333 qdrant/qdrant

# Or use cloud instance
# Update QDRANT_URL in .env
```

### Missing API Keys

Make sure all required keys are in `.env`:
- `OPENAI_API_KEY`
- `LANGCHAIN_API_KEY`
- `QDRANT_URL` (and optionally `QDRANT_API_KEY`)

### Import Errors

If you see import errors, make sure dependencies are installed:

```bash
pip install -r requirements.txt
```

## Next Steps

1. Review the examples in `examples/basic_usage.py`
2. Customize the agent workflow in `src/agent.py`
3. Add your own evaluation datasets in `src/evals.py`
4. Configure RAG pipeline parameters for your use case
5. Set up knowledge ingestion pipeline for your data sources
6. Cross-check design decisions against the requirement doc (see `Documentation/CODE_DOCUMENTATION.md`)

## Architecture Overview

```
Agent Workflow (LangGraph)
├── Plan Phase: Create todo list
├── Research Phase: Gather information
│   ├── Search similar devices (RAG)
│   └── Retrieve knowledge (Global + Client)
├── Create Documents Phase: Generate documents
│   └── Track transactions (Rollback support)
├── Review Phase: Review and revise
└── Context Compression: Manage context window

Evaluation System (LangSmith)
├── Mock API: Isolated testing environment
├── Completeness Evaluator
├── Correctness Evaluator
└── Safety Evaluator
```

## Support

For issues or questions, refer to:
- `README.md` for detailed documentation
- `examples/basic_usage.py` for code examples
- Source code comments for implementation details

