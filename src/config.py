"""Configuration settings for Formly agents."""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    """Application settings."""
    
    # API Keys
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    langchain_api_key: str = os.getenv("LANGCHAIN_API_KEY", "")
    
    # LangSmith Configuration
    langchain_tracing_v2: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    langchain_project: str = os.getenv("LANGCHAIN_PROJECT", "formly-agents")
    
    # Vector Database
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_api_key: Optional[str] = os.getenv("QDRANT_API_KEY")
    
    # API Configuration
    mock_api_url: str = os.getenv("MOCK_API_URL", "http://localhost:8001")
    production_api_url: str = os.getenv("PRODUCTION_API_URL", "http://localhost:8000")
    
    # Database
    database_url: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/formly")
    
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


