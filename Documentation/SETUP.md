# Setup Guide

## Complete Setup Instructions

### 1. System Requirements

- Python 3.9 or higher
- 8GB+ RAM recommended
- Internet connection for API calls

### 2. Install Python Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Set Up Qdrant Vector Database

#### Option A: Local Docker Instance (Recommended for Development)

```bash
docker run -d -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

#### Option B: Qdrant Cloud (Recommended for Production)

1. Sign up at https://cloud.qdrant.io
2. Create a cluster
3. Get your API key and URL
4. Update `.env` with credentials

### 4. Configure Environment Variables

```bash
# Copy example file
cp .env.example .env

# Edit .env file with your credentials
```

Required variables:

```env
# OpenAI API Key (required)
OPENAI_API_KEY=sk-...

# LangSmith API Key (required for evaluations)
LANGCHAIN_API_KEY=lsv2_...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=medical-documentation-agents

# Qdrant Configuration
QDRANT_URL=http://localhost:6333
# QDRANT_API_KEY=...  # Optional for local, required for cloud

# API Configuration (for evals)
MOCK_API_URL=http://localhost:8001
PRODUCTION_API_URL=http://localhost:8000
```

### 5. Get API Keys

#### OpenAI API Key
1. Go to https://platform.openai.com/api-keys
2. Create a new API key
3. Add to `.env` as `OPENAI_API_KEY`

#### LangSmith API Key
1. Go to https://smith.langchain.com
2. Sign up / Log in
3. Go to Settings > API Keys
4. Create a new API key
5. Add to `.env` as `LANGCHAIN_API_KEY`

### 6. Verify Installation

```bash
# Test imports
python -c "from src.agent import MedicalDocumentationAgent; print('✓ Imports successful')"

# Test Qdrant connection
python -c "from qdrant_client import QdrantClient; client = QdrantClient(url='http://localhost:6333'); print('✓ Qdrant connected')"
```

### 7. Initialize Data (Optional)

If you have existing data to index:

```python
from src.rag_pipeline import HybridRetrieval, SemanticChunker
from src.knowledge_retrieval import KnowledgeRetrieval

# Initialize components
rag = HybridRetrieval()
chunker = SemanticChunker()
kr = KnowledgeRetrieval()

# Index documents (example)
# chunks = chunker.chunk_document("doc_001", document_content)
# rag.index_chunks(chunks)

# Index knowledge chunks
# kr.index_knowledge_chunk(knowledge_chunk)
```

### 8. Run Tests

```bash
# Run basic agent test
python run_agent.py

# Run evaluations
python run_evals.py
```

## Development Setup

### For Development

1. Install development dependencies:

```bash
pip install pytest pytest-asyncio black flake8
```

2. Set up pre-commit hooks (optional):

```bash
pip install pre-commit
pre-commit install
```

3. Run linting:

```bash
flake8 src/
```

4. Format code:

```bash
black src/
```

## Production Setup

### For Production Deployment

1. Use environment-specific configuration:

```bash
# Production .env
PRODUCTION_API_URL=https://api.production.com
QDRANT_URL=https://your-cluster.qdrant.io
QDRANT_API_KEY=your_production_key
```

2. Set up monitoring:

```bash
# Enable LangSmith tracing
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=medical-documentation-agents-production
```

3. Configure logging:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

4. Use production-grade database for rollback storage:

```python
# Update src/rollback.py to use PostgreSQL/MySQL instead of in-memory
```

## Troubleshooting

### Common Issues

#### Issue: "Qdrant connection failed"

**Solution:**
- Check if Qdrant is running: `docker ps | grep qdrant`
- Verify URL in `.env`: `QDRANT_URL=http://localhost:6333`
- For cloud: Check API key and URL

#### Issue: "OpenAI API key invalid"

**Solution:**
- Verify key in `.env`: `OPENAI_API_KEY=sk-...`
- Check key has sufficient credits
- Verify key has access to required models

#### Issue: "LangSmith tracing not working"

**Solution:**
- Verify `LANGCHAIN_TRACING_V2=true` in `.env`
- Check `LANGCHAIN_API_KEY` is set
- Verify project name: `LANGCHAIN_PROJECT=medical-documentation-agents`

#### Issue: "Import errors"

**Solution:**
```bash
# Reinstall dependencies
pip install -r requirements.txt --upgrade

# Verify Python version
python --version  # Should be 3.9+
```

#### Issue: "Context window exceeded"

**Solution:**
- Reduce `context_window_limit` in `src/config.py`
- Lower `context_compression_threshold`
- Use smaller chunk sizes

## Next Steps

After setup:

1. Review `QUICKSTART.md` for usage examples
2. Read `README.md` for architecture details
3. Explore `examples/basic_usage.py` for code examples
4. Customize agent behavior in `src/agent.py`
5. Set up your evaluation datasets

## Support

For additional help:
- Check documentation in `README.md`
- Review code comments in source files
- Test with examples in `examples/`
- Check LangSmith dashboard for evaluation results

