# Code Documentation Guide

This document explains how the codebase maps to the requirement doc sections.

## Documentation Structure

All code files now include comprehensive docstrings that:
1. Reference the specific section of requirement doc they implement
2. Explain the design rationale
3. Provide implementation details
4. Include usage examples where relevant

## Section Mappings

### Section 1: Rollbacks (`src/rollback.py`)
- **RollbackManager**: Implements transaction tracking and rollback functionality
- **RollbackAPI**: Provides API layer for rollback operations
- Key methods reference Section 1 requirements

### Section 2: Evals (`src/mock_api.py`, `src/evals.py`)
- **MockDatabase**: Isolated database for safe evaluation
- **MockAPI**: Mock API that mimics production
- **AgentEvaluator**: LangSmith integration for evaluations
- All methods reference Section 2 safety requirements

### Section 3: RAG Pipeline (`src/rag_pipeline.py`)
- **HybridRetrieval**: Combines dense + sparse retrieval
- **SemanticChunker**: Paragraph-based chunking
- Methods reference Section 3 improvements

### Section 4: Knowledge Retrieval (`src/knowledge_retrieval.py`)
- Dual knowledge stores (global + client)
- Recency scoring and conflict detection
- References Section 4 architecture

### Section 5: Context Management (`src/context_manager.py`)
- Context segmentation by topic
- Relevance-based compression
- References Section 5 drift prevention

### Agent Orchestration (`src/agent.py`)
- Integrates all sections
- LangGraph workflow implementation
- References multiple sections

## Reading the Code

Each file includes:
1. Module-level docstring explaining the section
2. Class docstrings with design rationale
3. Method docstrings with implementation details
4. Inline comments for complex logic
5. References to specific document sections

## Example Structure

```python
"""
Module description with section reference.

Reference: requirement doc - Section X: [Topic]
"""

class ClassName:
    """
    Class description.
    
    Reference: requirement doc - Section X: "Specific requirement"
    """
    
    def method_name(self):
        """
        Method description.
        
        Reference: requirement doc - Section X: "Specific implementation detail"
        """
        # Implementation with inline comments
```




## Project Structure Overview

```
.
├── src/
│   ├── __init__.py
│   ├── config.py              # Configuration
│   ├── models.py              # Data models
│   ├── agent.py               # Main LangGraph agent
│   ├── tools.py               # Agent tools
│   ├── rag_pipeline.py        # RAG with hybrid retrieval
│   ├── knowledge_retrieval.py # Knowledge retrieval
│   ├── context_manager.py     # Context management
│   ├── rollback.py            # Rollback system
│   ├── mock_api.py            # Mock API for evals
│   └── evals.py               # LangSmith evaluations
├── examples/
│   └── basic_usage.py         # Usage examples
├── run_agent.py               # Run agent script
├── run_evals.py               # Run evaluations script
├── requirements.txt           # Dependencies
├── README.md                  # Main documentation
├── QUICKSTART.md              # Quick start guide
└── SETUP.md                   # Setup instructions
```

Use this map alongside the section breakdowns above to jump from requirement doc sections to their implementations.

