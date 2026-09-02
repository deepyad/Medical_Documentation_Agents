"""Configuration settings for Medical Documentation agents."""
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings.

    openai_api_key has no fallback: it's used everywhere (agent, retrieval,
    knowledge) at import time already, so failing fast with a clear error beats
    silently proceeding with an empty key that only breaks later. database_url
    intentionally stays optional here (not every workflow needs Postgres, e.g.
    eval/mock mode) — its own fail-fast check lives in src/db.py, applied only
    when Postgres-backed storage is actually used. See Documentation/
    ARCHITECTURE_DECISIONS.md, I1.
    """

    # API Keys
    openai_api_key: str
    langchain_api_key: Optional[str] = None

    # LLM (see Documentation/ARCHITECTURE_DECISIONS.md, B1 — default kept as the
    # existing model rather than guessed forward; override via OPENAI_MODEL)
    openai_model: str = "gpt-4-turbo-preview"

    # LangSmith Configuration
    langchain_tracing_v2: bool = False
    langchain_project: str = "medical-documentation-agents"

    # Vector Database
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None

    # API Configuration
    mock_api_url: str = "http://localhost:8001"
    production_api_url: str = "http://localhost:8000"

    # Database (optional — only required when Postgres-backed storage is used, see src/db.py)
    database_url: Optional[str] = None

    # Context Management
    context_window_limit: int = 8000  # Tokens before compression
    context_compression_threshold: float = 0.6  # Compress at 60% of context window

    # RAG Configuration
    embedding_model: str = "text-embedding-ada-002"
    chunk_size: int = 400
    chunk_overlap: int = 50
    top_k_retrieval: int = 10

    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
