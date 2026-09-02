"""Production API backed by Postgres.

Mirrors MockAPI's interface (src/mock_api.py) exactly so the agent's tools
(src/tools.py) can target either implementation without changing call sites.
MockAPI stays the isolated, resettable store used for evals; PostgresAPI is
the durable store used in production mode.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List

from src.db import get_session
from src.db_models import DocumentRecord, FormRecord


class PostgresAPI:
    """Production API for documents and forms, backed by real Postgres tables."""

    def get_document(self, document_id: str) -> Dict[str, Any]:
        with get_session() as session:
            record = session.get(DocumentRecord, document_id)
            if record is None:
                return {"error": "Document not found", "document_id": document_id}
            return self._document_to_dict(record)

    def create_document(self, document_data: Dict[str, Any]) -> Dict[str, Any]:
        document_id = document_data.get("id") or str(uuid.uuid4())
        with get_session() as session:
            record = DocumentRecord(
                id=document_id,
                type=document_data.get("type", ""),
                title=document_data.get("title", ""),
                content=document_data.get("content", ""),
                status=document_data.get("status", "draft"),
                client_id=document_data.get("client_id"),
                doc_metadata=document_data.get("metadata", {}),
                created_at=datetime.utcnow(),
            )
            session.add(record)
            session.flush()
            return self._document_to_dict(record)

    def update_document(self, document_id: str, document_data: Dict[str, Any]) -> Dict[str, Any]:
        with get_session() as session:
            record = session.get(DocumentRecord, document_id)
            if record is None:
                return self.create_document({**document_data, "id": document_id})

            if "content" in document_data:
                record.content = document_data["content"]
            if "title" in document_data:
                record.title = document_data["title"]
            if "status" in document_data:
                record.status = document_data["status"]
            if "metadata" in document_data:
                record.doc_metadata = {**(record.doc_metadata or {}), **document_data["metadata"]}
            record.updated_at = datetime.utcnow()
            session.flush()
            return self._document_to_dict(record)

    def delete_document(self, document_id: str) -> Dict[str, Any]:
        with get_session() as session:
            record = session.get(DocumentRecord, document_id)
            if record is None:
                return {"success": False, "document_id": document_id}
            session.delete(record)
            return {"success": True, "document_id": document_id}

    def get_form(self, form_id: str) -> Dict[str, Any]:
        with get_session() as session:
            record = session.get(FormRecord, form_id)
            if record is None:
                return {"error": "Form not found", "form_id": form_id}
            return self._form_to_dict(record)

    def update_form_answer(self, form_id: str, question_id: str, answer: Any) -> Dict[str, Any]:
        with get_session() as session:
            record = session.get(FormRecord, form_id)
            if record is None:
                return {"error": "Form not found", "form_id": form_id}
            record.answers = {**(record.answers or {}), question_id: answer}
            record.updated_at = datetime.utcnow()
            session.flush()
            return self._form_to_dict(record)

    def get_all_documents(self) -> List[Dict[str, Any]]:
        with get_session() as session:
            return [self._document_to_dict(r) for r in session.query(DocumentRecord).all()]

    def get_all_forms(self) -> List[Dict[str, Any]]:
        with get_session() as session:
            return [self._form_to_dict(r) for r in session.query(FormRecord).all()]

    @staticmethod
    def _document_to_dict(record: DocumentRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "type": record.type,
            "title": record.title,
            "content": record.content,
            "status": record.status,
            "client_id": record.client_id,
            "metadata": record.doc_metadata or {},
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    @staticmethod
    def _form_to_dict(record: FormRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "title": record.title,
            "client_id": record.client_id,
            "answers": record.answers or {},
            "metadata": record.form_metadata or {},
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }
