"""Data models for Formly agents."""
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Task status enumeration."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class KnowledgeType(str, Enum):
    """Knowledge store type."""
    GLOBAL = "global"  # Consultant knowledge
    CLIENT = "client"  # Client-specific knowledge


class DocumentType(str, Enum):
    """Document type enumeration."""
    REGULATORY = "regulatory"
    CLINICAL = "clinical"
    SIMILAR_DEVICES = "similar_devices"
    SUMMARY = "summary"


class Transaction(BaseModel):
    """Transaction model for rollback tracking."""
    transaction_id: str
    action_type: str  # write, delete, update
    resource_id: str
    resource_type: str
    previous_state: Dict[str, Any]
    new_state: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.now)
    client_id: Optional[str] = None
    status: TaskStatus = TaskStatus.COMPLETED


class TodoItem(BaseModel):
    """Todo item for task tracking."""
    id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: List[str] = Field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class DocumentChunk(BaseModel):
    """Document chunk for RAG."""
    chunk_id: str
    document_id: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None
    chunk_index: int = 0


class KnowledgeChunk(BaseModel):
    """Knowledge chunk for retrieval."""
    chunk_id: str
    content: str
    knowledge_type: KnowledgeType
    client_id: Optional[str] = None
    source: str  # slack, discord, call, etc.
    timestamp: datetime
    confidence: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[List[float]] = None


class AgentState(BaseModel):
    """Agent state for LangGraph."""
    task_description: str
    todos: List[TodoItem] = Field(default_factory=list)
    documents: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    context_segments: Dict[str, List[str]] = Field(default_factory=dict)
    transactions: List[Transaction] = Field(default_factory=list)
    current_step: int = 0
    client_id: Optional[str] = None
    device_info: Optional[Dict[str, Any]] = None
    retrieved_knowledge: List[KnowledgeChunk] = Field(default_factory=list)
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class RetrievalResult(BaseModel):
    """Retrieval result from RAG pipeline."""
    chunk_id: str
    content: str
    score: float
    metadata: Dict[str, Any]
    document_id: str

