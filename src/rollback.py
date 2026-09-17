"""
Rollback mechanism for agent actions.

This module implements Section 1 of the requirement doc: "Rollbacks for Destructive Actions".

The rollback system allows agents to perform autonomous, potentially destructive actions (write, delete,
update documents or form answers) while maintaining the ability to undo changes if mistakes are detected.

Key Design Principles (from Section 1):
- Maintain snapshots/backups before destructive actions
- Track each action with a unique transaction ID
- Provide rollback API endpoint functionality
- Support atomicity and data consistency
- Keep detailed audit logs

Implementation Strategy:
1. Transaction Management: Each destructive action creates a transaction record with before/after states
2. State Snapshot: Capture previous state before executing action
3. Rollback API: Provide endpoint-like functionality to rollback transactions
4. Audit Logging: Maintain transaction log for all changes

Storage is pluggable (see RollbackStorage below): InMemoryRollbackStorage for eval-mode isolation,
PostgresRollbackStorage for a durable production audit trail.

Reference: requirement doc - Section 1: Rollbacks
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import uuid

import sentry_sdk

from src.models import Transaction, TaskStatus
from src.observability import get_logger

logger = get_logger(__name__)


class RollbackStorage(ABC):
    """Storage backend interface for rollback transactions."""

    @abstractmethod
    def save(self, transaction: Transaction) -> None:
        """Persist a transaction (insert or update by transaction_id)."""

    @abstractmethod
    def get(self, transaction_id: str) -> Optional[Transaction]:
        """Fetch a transaction by ID."""

    @abstractmethod
    def list(
        self,
        client_id: Optional[str] = None,
        action_type: Optional[str] = None
    ) -> List[Transaction]:
        """List transactions, optionally filtered, newest first."""


class InMemoryRollbackStorage(RollbackStorage):
    """
    Process-local, non-durable storage.

    Used as the default and for eval mode, where transactions should stay isolated
    to the run and not pollute the durable production audit trail.
    """

    def __init__(self):
        self._transactions: Dict[str, Transaction] = {}

    def save(self, transaction: Transaction) -> None:
        self._transactions[transaction.transaction_id] = transaction

    def get(self, transaction_id: str) -> Optional[Transaction]:
        return self._transactions.get(transaction_id)

    def list(
        self,
        client_id: Optional[str] = None,
        action_type: Optional[str] = None
    ) -> List[Transaction]:
        transactions = list(self._transactions.values())

        if client_id:
            transactions = [t for t in transactions if t.client_id == client_id]
        if action_type:
            transactions = [t for t in transactions if t.action_type == action_type]

        return sorted(transactions, key=lambda t: t.timestamp, reverse=True)


class PostgresRollbackStorage(RollbackStorage):
    """
    Durable storage backed by Postgres.

    Implements ADR E1 (Documentation/ARCHITECTURE_DECISIONS.md): transactions survive
    process restarts and are shared across workers, giving the audit trail real
    persistence instead of an in-memory dict.
    """

    def save(self, transaction: Transaction) -> None:
        from src.db import get_session
        from src.db_models import TransactionRecord

        with get_session() as session:
            record = session.get(TransactionRecord, transaction.transaction_id)
            if record is None:
                record = TransactionRecord(transaction_id=transaction.transaction_id)
                session.add(record)

            record.action_type = transaction.action_type
            record.resource_id = transaction.resource_id
            record.resource_type = transaction.resource_type
            record.previous_state = transaction.previous_state
            record.new_state = transaction.new_state
            record.timestamp = transaction.timestamp
            record.client_id = transaction.client_id
            record.status = transaction.status.value

    def get(self, transaction_id: str) -> Optional[Transaction]:
        from src.db import get_session
        from src.db_models import TransactionRecord

        with get_session() as session:
            record = session.get(TransactionRecord, transaction_id)
            return self._to_model(record) if record else None

    def list(
        self,
        client_id: Optional[str] = None,
        action_type: Optional[str] = None
    ) -> List[Transaction]:
        from src.db import get_session
        from src.db_models import TransactionRecord

        with get_session() as session:
            query = session.query(TransactionRecord)
            if client_id:
                query = query.filter(TransactionRecord.client_id == client_id)
            if action_type:
                query = query.filter(TransactionRecord.action_type == action_type)

            records = query.order_by(TransactionRecord.timestamp.desc()).all()
            return [self._to_model(record) for record in records]

    @staticmethod
    def _to_model(record) -> Transaction:
        return Transaction(
            transaction_id=record.transaction_id,
            action_type=record.action_type,
            resource_id=record.resource_id,
            resource_type=record.resource_type,
            previous_state=record.previous_state,
            new_state=record.new_state,
            timestamp=record.timestamp,
            client_id=record.client_id,
            status=TaskStatus(record.status),
        )


class RollbackManager:
    """
    Manages rollbacks for destructive agent actions.

    This class implements the core rollback functionality as described in Section 1 of the requirement doc.
    It delegates persistence to a pluggable RollbackStorage backend and provides methods to create,
    track, and rollback transactions.

    Reference: requirement doc - Section 1: "Transaction Management with a Log"
    """

    def __init__(self, storage: Optional[RollbackStorage] = None):
        """
        Initialize rollback manager.

        Args:
            storage: Storage backend to use. Defaults to InMemoryRollbackStorage so the
                    manager works without a database configured. Pass PostgresRollbackStorage()
                    for a durable, production audit trail (see ADR E1).
        """
        self.storage = storage or InMemoryRollbackStorage()

    def create_transaction(
        self,
        action_type: str,
        resource_id: str,
        resource_type: str,
        previous_state: Dict[str, Any],
        new_state: Dict[str, Any],
        client_id: Optional[str] = None
    ) -> str:
        """
        Create a transaction record for a destructive action.

        Args:
            action_type: Type of action (write, delete, update)
            resource_id: ID of the resource being modified
            resource_type: Type of resource (document, form, etc.)
            previous_state: State before the action (snapshot for rollback)
            new_state: State after the action (for verification)
            client_id: Optional client ID for multi-tenant scenarios

        Returns:
            Transaction ID: Unique identifier for this transaction

        Reference: requirement doc - Section 1: "Track Each Action with an ID or Transaction ID"
        """
        transaction_id = str(uuid.uuid4())
        transaction = Transaction(
            transaction_id=transaction_id,
            action_type=action_type,
            resource_id=resource_id,
            resource_type=resource_type,
            previous_state=previous_state,
            new_state=new_state,
            client_id=client_id
        )

        self.storage.save(transaction)

        return transaction_id

    def rollback(self, transaction_id: str) -> Dict[str, Any]:
        """
        Rollback a transaction.

        Args:
            transaction_id: ID of transaction to rollback

        Returns:
            Dict containing success, previous_state (for the caller to restore), and
            transaction/resource identifiers, or an error message if not found.

        Reference: requirement doc - Section 1: "Design a Rollback API Endpoint"
        Reference: requirement doc - Section 1: "User Invokes Rollback on Realizing a Mistake"
        """
        transaction = self.storage.get(transaction_id)

        if transaction is None:
            return {
                "success": False,
                "error": f"Transaction {transaction_id} not found"
            }

        transaction = transaction.model_copy(update={"status": TaskStatus.ROLLED_BACK})
        self.storage.save(transaction)

        return {
            "success": True,
            "transaction_id": transaction_id,
            "previous_state": transaction.previous_state,
            "action_type": transaction.action_type,
            "resource_id": transaction.resource_id,
            "resource_type": transaction.resource_type
        }

    def rollback_group(self, transaction_ids: List[str]) -> Dict[str, Any]:
        """
        Roll back a batch of related transactions as a unit, in reverse order.

        Implements ADR E2 (multi-resource transaction atomicity). Rather than
        storing a group id (which would require extending Transaction/
        TransactionRecord and both RollbackStorage backends), the caller
        supplies the transaction_ids it already collected while performing
        the batch — e.g. one document creation per loop iteration.

        Args:
            transaction_ids: IDs in original creation order. Rolled back in
                             reverse, since undoing must unwind a batch in
                             the opposite order it was built (e.g. don't try
                             to update a document a later step deleted).

        Returns:
            Dict with "success" (True only if every rollback succeeded),
            "rolled_back" (results for transactions undone so far), and
            "failed" (the result that stopped the rollback, if any). Stops
            at the first failure rather than continuing silently past it —
            a partially-rolled-back batch needs a human to look at it, not
            a best-effort sweep that hides which pieces didn't undo cleanly.
        """
        rolled_back = []

        for transaction_id in reversed(transaction_ids):
            result = self.rollback(transaction_id)
            if not result.get("success"):
                return {
                    "success": False,
                    "rolled_back": rolled_back,
                    "failed": result
                }
            rolled_back.append(result)

        return {
            "success": True,
            "rolled_back": rolled_back,
            "failed": None
        }

    def get_transaction(self, transaction_id: str) -> Optional[Transaction]:
        """Get transaction by ID."""
        return self.storage.get(transaction_id)

    def list_transactions(
        self,
        client_id: Optional[str] = None,
        action_type: Optional[str] = None
    ) -> List[Transaction]:
        """
        List transactions with optional filters.

        Reference: requirement doc - Section 1: "Audit and Version Control"
        """
        return self.storage.list(client_id=client_id, action_type=action_type)


class RollbackAPI:
    """
    API layer for rollback operations.

    This class provides the high-level API interface for rollback operations,
    implementing the "Design a Rollback API Endpoint" requirement from Section 1.

    Reference: requirement doc - Section 1: "Design a Rollback API Endpoint"
    """

    def __init__(self, rollback_manager: RollbackManager):
        """
        Initialize rollback API.

        Args:
            rollback_manager: RollbackManager instance to use for transaction management
        """
        self.rollback_manager = rollback_manager

    def execute_with_rollback(
        self,
        action_type: str,
        resource_id: str,
        resource_type: str,
        action_func: callable,
        get_state_func: callable,
        update_state_func: callable,
        client_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute an action with automatic rollback tracking.

        Example Workflow (from Section 1):
        1. Before executing a destructive API call, save the current state or data snapshot
        2. Perform the action
        3. If a user or system detects an error or mistake, trigger a rollback
           by invoking the undo script or restoring the snapshot
        4. Confirm the system returns to the prior, consistent state

        Args:
            action_type: Type of action (write, delete, update)
            resource_id: Resource ID being modified
            resource_type: Type of resource (document, form, etc.)
            action_func: Function to execute the actual action
            get_state_func: Function to get current state of a resource
            update_state_func: Function to update resource state (used by rollback to restore)
            client_id: Optional client ID for multi-tenant scenarios

        Returns:
            Dict containing success, result, transaction_id, or an error message.

        Reference: requirement doc - Section 1: "Example Workflow"
        """
        previous_state = get_state_func(resource_id)

        try:
            result = action_func()
            new_state = get_state_func(resource_id)

            transaction_id = self.rollback_manager.create_transaction(
                action_type=action_type,
                resource_id=resource_id,
                resource_type=resource_type,
                previous_state=previous_state,
                new_state=new_state,
                client_id=client_id
            )

            return {
                "success": True,
                "result": result,
                "transaction_id": transaction_id
            }
        except Exception as e:
            # This is the only place this exception is ever seen — it's
            # converted to a return value below, not re-raised — so this is
            # also the only chance to log/track it. See ADR J2.
            logger.error(
                "rollback_action_failed",
                action_type=action_type,
                resource_id=resource_id,
                resource_type=resource_type,
                client_id=client_id,
                error=str(e),
                exc_info=True,
            )
            sentry_sdk.capture_exception(e)

            return {
                "success": False,
                "error": str(e)
            }

    def rollback_transaction(self, transaction_id: str) -> Dict[str, Any]:
        """
        Rollback a transaction via API.

        Reference: requirement doc - Section 1: "User Invokes Rollback on Realizing a Mistake"
        """
        return self.rollback_manager.rollback(transaction_id)

    def rollback_group(self, transaction_ids: List[str]) -> Dict[str, Any]:
        """
        Rollback a batch of related transactions as a unit. See ADR E2.
        """
        return self.rollback_manager.rollback_group(transaction_ids)
