"""
Mock API for evaluation system.

This module implements Section 2 of the requirement doc: "Evals for Agent Traces".

The evaluation system allows agents to run evals with steps that call tools connected to a production
API/database without actually changing the production data. This is achieved through a mock/shadow API
layer that simulates the production API but uses an isolated database.

Key Design Principles (from Section 2):
- Create a Mock or Shadow API Layer that mimics production API
- Use Data Snapshot and Loading from production data
- Maintain Transaction Logging and Isolation
- Provide Reset Capability for clean eval runs
- Ensure Input-Output Consistency with production

Implementation Strategy:
1. Mock API: Alternative version of production API with same endpoints
2. Isolated Database: Ephemeral database that doesn't affect production
3. Snapshot Loading: Load production data snapshots for realistic testing
4. Transaction Logging: Track all changes for analysis
5. Reset Capability: Clean state between eval runs

Reference: requirement doc - Section 2: Evals
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid
import copy


class MockDatabase:
    """
    In-memory mock database for eval testing.
    
    This class implements the "Isolated Database" requirement from Section 2.
    It uses an in-memory data structure that replicates production data shapes
    but doesn't affect the real production database.
    
    Key Features:
    - Snapshot-based initialization (loads production-like data)
    - Transaction logging for analysis
    - Reset capability to restore initial state
    - Isolation from production data
    
    Reference: requirement doc - Section 2: "Create a Mock or Shadow API Layer"
    Reference: requirement doc - Section 2: "Data Snapshot and Loading"
    """
    
    def __init__(self, snapshot_data: Optional[Dict[str, Any]] = None):
        """
        Initialize mock database with optional snapshot data.
        
        Implements "Data Snapshot and Loading" from Section 2. Periodically take
        snapshots of production data and load them into the mock environment so
        the agent works with current-like data but in an isolated context.
        
        Args:
            snapshot_data: Optional snapshot of production data
                          This should be a dictionary with structure:
                          {
                              "documents": {doc_id: doc_data, ...},
                              "forms": {form_id: form_data, ...},
                              ...
                          }
                          In production, this would be loaded from a periodic export
                          of production data (e.g., nightly batch job)
        
        Reference: requirement doc - Section 2: "Data Snapshot and Loading"
        Reference: requirement doc - Section 2: "Periodically snapshot production data"
        """
        # Deep copy to ensure isolation from source data
        self.data = copy.deepcopy(snapshot_data) if snapshot_data else {}
        self.transaction_log: List[Dict[str, Any]] = []
        # Store initial snapshot for reset capability
        self.initial_snapshot = copy.deepcopy(self.data)
    
    def get(self, resource_type: str, resource_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a resource from mock database.
        
        Implements read-only access to mock data. This mimics production API
        read operations but uses the isolated mock database.
        
        Args:
            resource_type: Type of resource (documents, forms, etc.)
            resource_id: ID of the resource
            
        Returns:
            Resource data if found, None otherwise
        """
        collection = self.data.get(resource_type, {})
        return collection.get(resource_id)
    
    def create(
        self,
        resource_type: str,
        resource_id: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a resource in mock database.
        
        Implements destructive write operations in the isolated mock environment.
        All changes are tracked in the transaction log for analysis but don't
        affect production data.
        
        Args:
            resource_type: Type of resource (documents, forms, etc.)
            resource_id: ID for the new resource
            data: Resource data
            
        Returns:
            Created resource with metadata (id, created_at)
        
        Reference: requirement doc - Section 2: "Transaction Logging and Isolation"
        """
        if resource_type not in self.data:
            self.data[resource_type] = {}
        
        self.data[resource_type][resource_id] = {
            **data,
            "id": resource_id,
            "created_at": datetime.now().isoformat()
        }
        
        # Log transaction for analysis (implements "Transaction Logging" from Section 2)
        self.transaction_log.append({
            "action": "create",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "timestamp": datetime.now().isoformat()
        })
        
        return self.data[resource_type][resource_id]
    
    def update(
        self,
        resource_type: str,
        resource_id: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update a resource in mock database.
        
        Implements destructive update operations. Changes are isolated to the
        mock database and logged for analysis.
        
        Args:
            resource_type: Type of resource
            resource_id: ID of resource to update
            data: Updated data (merged with existing)
            
        Returns:
            Updated resource with metadata
        """
        if resource_type not in self.data:
            self.data[resource_type] = {}
        
        if resource_id not in self.data[resource_type]:
            return self.create(resource_type, resource_id, data)
        
        self.data[resource_type][resource_id].update({
            **data,
            "updated_at": datetime.now().isoformat()
        })
        
        # Log transaction
        self.transaction_log.append({
            "action": "update",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "timestamp": datetime.now().isoformat()
        })
        
        return self.data[resource_type][resource_id]
    
    def delete(self, resource_type: str, resource_id: str) -> bool:
        """
        Delete a resource from mock database.
        
        Implements destructive delete operations in isolated environment.
        
        Args:
            resource_type: Type of resource
            resource_id: ID of resource to delete
            
        Returns:
            True if deleted, False if not found
        """
        if resource_type in self.data and resource_id in self.data[resource_type]:
            del self.data[resource_type][resource_id]
            
            # Log transaction
            self.transaction_log.append({
                "action": "delete",
                "resource_type": resource_type,
                "resource_id": resource_id,
                "timestamp": datetime.now().isoformat()
            })
            
            return True
        return False
    
    def reset(self):
        """
        Reset database to initial snapshot.
        
        This implements "Reset Capability" from Section 2. After each eval run,
        the database can be reset to the initial snapshot state, ensuring clean
        isolated runs for repeated evaluations.
        
        This is critical for:
        - Ensuring eval runs start from the same known clean state
        - Preventing side effects from previous eval runs
        - Maintaining reproducibility of evaluations
        
        Reference: requirement doc - Section 2: "Undo/Reset Capability"
        Reference: requirement doc - Section 2: "Reset the mock DB to initial snapshot state"
        """
        self.data = copy.deepcopy(self.initial_snapshot)
        self.transaction_log = []
    
    def get_all(self, resource_type: str) -> List[Dict[str, Any]]:
        """
        Get all resources of a type.
        
        Utility method for retrieving all resources of a given type.
        Useful for analysis and verification.
        
        Args:
            resource_type: Type of resources to retrieve
            
        Returns:
            List of all resources of the specified type
        """
        collection = self.data.get(resource_type, {})
        return list(collection.values())


class MockAPI:
    """
    Mock API that mimics production API but uses isolated database.
    
    This class implements the "Create a Mock or Shadow API Layer" requirement from Section 2.
    It provides the same interface as the production API (same endpoints, same request/response
    formats) but internally uses the MockDatabase for all operations, ensuring complete
    isolation from production data.
    
    Key Features:
    - Same interface as production API (drop-in replacement)
    - Isolated database (no production impact)
    - Transaction logging for analysis
    - Reset capability for clean eval runs
    - Input-Output consistency with production
    
    Implementation Details (from Section 2):
    1. Mock API mimics production API interface (same endpoints, same request/response formats)
    2. Internally connects to MockDatabase instead of production database
    3. All writes modify mock DB state and log changes
    4. Read operations fetch from mock DB
    5. Reset capability restores initial state
    
    Reference: requirement doc - Section 2: "Create a Mock or Shadow API Layer"
    Reference: requirement doc - Section 2: "The mock API mimics the production API interface"
    """
    
    def __init__(self, snapshot_data: Optional[Dict[str, Any]] = None):
        """
        Initialize mock API with optional snapshot data.
        
        Args:
            snapshot_data: Optional snapshot of production data to initialize with
                          This allows the mock API to work with realistic, current-like data
                          without affecting production
        
        Reference: requirement doc - Section 2: "Data Snapshot and Loading"
        """
        self.db = MockDatabase(snapshot_data)
    
    def get_document(self, document_id: str) -> Dict[str, Any]:
        """
        Get a document (read-only).
        
        Mimics production API document retrieval but uses mock database.
        This is a safe read operation that doesn't modify data.
        
        Args:
            document_id: Document ID to retrieve
            
        Returns:
            Document data or error message if not found
        """
        doc = self.db.get("documents", document_id)
        if not doc:
            return {"error": "Document not found", "document_id": document_id}
        return doc
    
    def create_document(self, document_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a document (destructive).
        
        Mimics production API document creation but writes to mock database.
        This operation is tracked in transaction log but doesn't affect production.
        
        Args:
            document_data: Document data to create
            
        Returns:
            Created document with metadata
        
        Reference: requirement doc - Section 2: "Destructive calls modify the mock DB state"
        """
        document_id = document_data.get("id") or str(uuid.uuid4())
        return self.db.create("documents", document_id, document_data)
    
    def update_document(
        self,
        document_id: str,
        document_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update a document (destructive).
        
        Mimics production API document update but modifies mock database only.
        
        Args:
            document_id: Document ID to update
            document_data: Updated document data
            
        Returns:
            Updated document
        """
        return self.db.update("documents", document_id, document_data)
    
    def delete_document(self, document_id: str) -> Dict[str, Any]:
        """
        Delete a document (destructive).
        
        Mimics production API document deletion but only affects mock database.
        
        Args:
            document_id: Document ID to delete
            
        Returns:
            Deletion result with success status
        """
        success = self.db.delete("documents", document_id)
        return {"success": success, "document_id": document_id}
    
    def get_form(self, form_id: str) -> Dict[str, Any]:
        """
        Get a form (read-only).
        
        Mimics production API form retrieval.
        
        Args:
            form_id: Form ID to retrieve
            
        Returns:
            Form data or error message if not found
        """
        form = self.db.get("forms", form_id)
        if not form:
            return {"error": "Form not found", "form_id": form_id}
        return form
    
    def update_form_answer(
        self,
        form_id: str,
        question_id: str,
        answer: Any
    ) -> Dict[str, Any]:
        """
        Update a form answer (destructive).
        
        Mimics production API form answer update. This is a destructive operation
        that would normally change production data, but here it only affects the
        mock database.
        
        Args:
            form_id: Form ID
            question_id: Question ID within the form
            answer: Answer value
            
        Returns:
            Updated form
        
        Reference: requirement doc - Section 2: Example of destructive action that
                   would normally affect production but is safe in mock API
        """
        form = self.db.get("forms", form_id)
        if not form:
            return {"error": "Form not found", "form_id": form_id}
        
        if "answers" not in form:
            form["answers"] = {}
        
        form["answers"][question_id] = answer
        return self.db.update("forms", form_id, form)
    
    def reset_database(self):
        """
        Reset database to initial state (for eval cleanup).
        
        This method is called after each eval run to restore the mock database
        to its initial snapshot state. This ensures:
        - Clean state for each eval run
        - Reproducibility of evaluations
        - No side effects from previous runs
        
        Reference: requirement doc - Section 2: "Reset the mock DB to initial snapshot state"
        Reference: requirement doc - Section 2: "This rollback capability ensures repeated evals
                   start from the same known clean state"
        """
        self.db.reset()
    
    def get_transaction_log(self) -> List[Dict[str, Any]]:
        """
        Get transaction log for analysis.
        
        Returns all transactions performed on the mock database. This is useful for:
        - Analyzing agent behavior during evals
        - Verifying correct operations
        - Debugging issues
        - Performance analysis
        
        Returns:
            List of transaction records
        
        Reference: requirement doc - Section 2: "Action Tracking: Maintain a transaction or
                   change log of all API writes during each eval run for auditability"
        """
        return self.db.transaction_log
    
    def get_all_documents(self) -> List[Dict[str, Any]]:
        """
        Get all documents.
        
        Utility method for retrieving all documents from mock database.
        Useful for verification and analysis.
        
        Returns:
            List of all documents
        """
        return self.db.get_all("documents")
    
    def get_all_forms(self) -> List[Dict[str, Any]]:
        """
        Get all forms.
        
        Utility method for retrieving all forms from mock database.
        
        Returns:
            List of all forms
        """
        return self.db.get_all("forms")
