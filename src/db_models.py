"""SQLAlchemy ORM models for Postgres-backed persistence.

These mirror the shapes previously held only in-memory by RollbackManager
(src/rollback.py) and MockDatabase (src/mock_api.py), so the same data can
survive process restarts and be shared across workers.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB

from src.db import Base


class TransactionRecord(Base):
    """Persisted rollback transaction (mirrors src.models.Transaction)."""

    __tablename__ = "transactions"

    transaction_id = Column(String, primary_key=True)
    action_type = Column(String, nullable=False)
    resource_id = Column(String, nullable=False)
    resource_type = Column(String, nullable=False)
    previous_state = Column(JSONB, nullable=False)
    new_state = Column(JSONB, nullable=False)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow)
    client_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="completed")


class DocumentRecord(Base):
    """Persisted regulatory document."""

    __tablename__ = "documents"

    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    content = Column(String, nullable=False, default="")
    status = Column(String, nullable=False, default="draft")
    client_id = Column(String, nullable=True, index=True)
    doc_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)


class FormRecord(Base):
    """Persisted form and its answers."""

    __tablename__ = "forms"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=True)
    client_id = Column(String, nullable=True, index=True)
    answers = Column(JSONB, nullable=False, default=dict)
    form_metadata = Column("metadata", JSONB, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)
