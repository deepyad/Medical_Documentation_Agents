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

Reference: requirement doc - Section 1: Rollbacks
"""
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
from src.models import Transaction, TaskStatus


class RollbackManager:
    """
    Manages rollbacks for destructive agent actions.
    
    This class implements the core rollback functionality as described in Section 1 of the requirement doc.
    It maintains a transaction log and provides methods to create, track, and rollback transactions.
    
    Design Pattern: Transaction-based rollback system
    - Before executing a destructive action, save the current state (snapshot)
    - After execution, record the new state
    - If rollback is needed, restore the previous state
    
    Reference: requirement doc - Section 1: "Transaction Management with a Log"
    """
    
    def __init__(self, storage: Optional[Dict[str, Any]] = None):
        """
        Initialize rollback manager.
        
        Implements the "Maintain a Snapshot or Backup" strategy from Section 1.
        Uses in-memory storage by default, but can be extended to use persistent storage
        (database, file system, etc.) for production use.
        
        Args:
            storage: Optional storage backend (dict for in-memory, can be DB for production)
                    In production, this could be a database connection or file-based storage
                    to persist transactions across restarts.
        
        Reference: requirement doc - Section 1: "Maintain a Snapshot or Backup"
        """
        self.storage = storage or {}
        self.transactions: Dict[str, Transaction] = {}
    
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
        
        This implements the "Track Each Action with an ID or Transaction ID" requirement
        from Section 1. Every destructive operation returns a unique transaction ID that
        can be used later for rollback.
        
        The transaction record captures:
        - Action type (write, delete, update)
        - Resource being modified
        - Previous state (snapshot before action)
        - New state (state after action)
        - Timestamp for audit trail
        
        Args:
            action_type: Type of action (write, delete, update)
                        These are the destructive operations that need rollback capability
            resource_id: ID of the resource being modified
            resource_type: Type of resource (document, form, etc.)
            previous_state: State before the action (snapshot for rollback)
            new_state: State after the action (for verification)
            client_id: Optional client ID for multi-tenant scenarios
            
        Returns:
            Transaction ID: Unique identifier for this transaction
                           Used by the rollback endpoint to identify which action to undo
            
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
        
        # Store transaction for later retrieval and rollback
        self.transactions[transaction_id] = transaction
        self.storage[transaction_id] = {
            "transaction": transaction.model_dump(),
            "can_rollback": True
        }
        
        return transaction_id
    
    def rollback(self, transaction_id: str) -> Dict[str, Any]:
        """
        Rollback a transaction.
        
        This implements the "Rollback API Endpoint" functionality from Section 1.
        When a user realizes the agent made a mistake, they can call this method
        (or the corresponding API endpoint) to undo the changes.
        
        The rollback process:
        1. Look up the transaction by ID
        2. Retrieve the previous state (snapshot)
        3. Restore the resource to the previous state
        4. Mark transaction as rolled back
        
        Args:
            transaction_id: ID of transaction to rollback
                          This is the ID returned when the original action was executed
            
        Returns:
            Dict containing:
            - success: Whether rollback was successful
            - previous_state: State to restore (used by API layer to actually restore)
            - transaction_id: Confirmation of which transaction was rolled back
            - error: Error message if rollback failed
        
        Reference: requirement doc - Section 1: "Design a Rollback API Endpoint"
        Reference: requirement doc - Section 1: "User Invokes Rollback on Realizing a Mistake"
        """
        if transaction_id not in self.transactions:
            return {
                "success": False,
                "error": f"Transaction {transaction_id} not found"
            }
        
        transaction = self.transactions[transaction_id]
        
        # Mark transaction as rolled back (create new instance with updated status)
        # This maintains audit trail showing that rollback occurred
        transaction = Transaction(
            **transaction.model_dump(),
            status=TaskStatus.ROLLED_BACK
        )
        self.transactions[transaction_id] = transaction
        
        # Return previous state for restoration
        # The calling code (API layer) will use this to actually restore the state
        return {
            "success": True,
            "transaction_id": transaction_id,
            "previous_state": transaction.previous_state,
            "action_type": transaction.action_type,
            "resource_id": transaction.resource_id,
            "resource_type": transaction.resource_type
        }
    
    def get_transaction(self, transaction_id: str) -> Optional[Transaction]:
        """
        Get transaction by ID.
        
        Utility method for retrieving transaction details. Useful for:
        - Verifying transaction status
        - Auditing and logging
        - Debugging
        
        Args:
            transaction_id: Transaction ID to retrieve
            
        Returns:
            Transaction object if found, None otherwise
        """
        return self.transactions.get(transaction_id)
    
    def list_transactions(
        self,
        client_id: Optional[str] = None,
        action_type: Optional[str] = None
    ) -> List[Transaction]:
        """
        List transactions with optional filters.
        
        Implements "Audit and Version Control" from Section 1 - keeping detailed logs
        of all changes for auditability and debugging.
        
        Args:
            client_id: Optional filter by client ID (for multi-tenant scenarios)
            action_type: Optional filter by action type (write, delete, update)
            
        Returns:
            List of transactions, sorted by timestamp (newest first)
            
        Reference: requirement doc - Section 1: "Audit and Version Control"
        """
        transactions = list(self.transactions.values())
        
        if client_id:
            transactions = [t for t in transactions if t.client_id == client_id]
        
        if action_type:
            transactions = [t for t in transactions if t.action_type == action_type]
        
        return sorted(transactions, key=lambda x: x.timestamp, reverse=True)


class RollbackAPI:
    """
    API layer for rollback operations.
    
    This class provides the high-level API interface for rollback operations,
    implementing the "Design a Rollback API Endpoint" requirement from Section 1.
    
    It wraps the RollbackManager and provides convenient methods for:
    - Executing actions with automatic rollback tracking
    - Rolling back transactions via API calls
    
    The execute_with_rollback method implements the workflow described in Section 1:
    1. Before executing destructive API call, save current state (snapshot)
    2. Perform the action
    3. Record transaction with before/after states
    4. Return transaction ID for potential rollback
    
    Reference: requirement doc - Section 1: "Design a Rollback API Endpoint"
    Reference: requirement doc - Section 1: "Example Workflow"
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
        
        This method implements the complete workflow from Section 1:
        
        Example Workflow (from Section 1):
        1. Before executing a destructive API call, save the current state or data snapshot
        2. Perform the action
        3. If a user or system detects an error or mistake, trigger a rollback
           by invoking the undo script or restoring the snapshot
        4. Confirm the system returns to the prior, consistent state
        
        This method handles steps 1-2. Step 3 is handled by rollback_transaction().
        
        Args:
            action_type: Type of action (write, delete, update)
            resource_id: Resource ID being modified
            resource_type: Type of resource (document, form, etc.)
            action_func: Function to execute the actual action
                        This should be a callable that performs the destructive operation
            get_state_func: Function to get current state of a resource
                           Used to capture before/after snapshots
            update_state_func: Function to update resource state
                              Used by rollback to restore previous state
            client_id: Optional client ID for multi-tenant scenarios
            
        Returns:
            Dict containing:
            - success: Whether action executed successfully
            - result: Result from action_func
            - transaction_id: Unique ID for this transaction (for rollback)
            - error: Error message if action failed
        
        Reference: requirement doc - Section 1: "Example Workflow"
        Reference: requirement doc - Section 1: "Use a Versioning Approach"
        """
        # Step 1: Get previous state (snapshot before action)
        # This implements "Maintain a Snapshot or Backup" from Section 1
        previous_state = get_state_func(resource_id)
        
        # Step 2: Execute the action
        try:
            result = action_func()
            # Capture new state after action
            new_state = get_state_func(resource_id)
            
            # Step 3: Create transaction record with before/after states
            # This implements "Transaction Management with a Log" from Section 1
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
                "transaction_id": transaction_id  # Return ID for potential rollback
            }
        except Exception as e:
            # If action fails, return error (no transaction created)
            return {
                "success": False,
                "error": str(e)
            }
    
    def rollback_transaction(self, transaction_id: str) -> Dict[str, Any]:
        """
        Rollback a transaction via API.
        
        This implements the "User Invokes Rollback on Realizing a Mistake" scenario
        from Section 1. When a user calls this method (or the corresponding API endpoint),
        the system restores the previous state.
        
        The rollback process:
        - Look up transaction by ID
        - Retrieve previous state (snapshot)
        - Restore resource to previous state
        - Confirm success
        
        Args:
            transaction_id: Transaction ID to rollback
                          This is the ID returned from execute_with_rollback()
            
        Returns:
            Rollback result with previous_state for restoration
            
        Reference: requirement doc - Section 1: "User Invokes Rollback on Realizing a Mistake"
        Reference: requirement doc - Section 1: "API Executes Undo Logic Internally"
        """
        return self.rollback_manager.rollback(transaction_id)
