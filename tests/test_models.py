"""Unit tests for src/models.py — pydantic model defaults and validation."""
import pytest
from pydantic import ValidationError

from src.models import (
    AgentState,
    DocumentType,
    KnowledgeType,
    PlanOutput,
    PlannedTodo,
    TaskStatus,
    Transaction,
)


class TestTaskStatus:
    def test_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.ROLLED_BACK == "rolled_back"


class TestTransaction:
    def test_defaults(self):
        transaction = Transaction(
            transaction_id="t1",
            action_type="create",
            resource_id="doc_1",
            resource_type="document",
            previous_state={},
            new_state={"a": 1},
        )

        assert transaction.status == TaskStatus.COMPLETED
        assert transaction.client_id is None
        assert transaction.timestamp is not None

    def test_requires_core_fields(self):
        with pytest.raises(ValidationError):
            Transaction(action_type="create")  # missing transaction_id, resource_id, etc.


class TestAgentState:
    def test_defaults(self):
        state = AgentState(task_description="Create documents for device X")

        assert state.todos == []
        assert state.documents == {}
        assert state.tool_errors == []
        assert state.error is None
        assert state.client_id is None

    def test_requires_task_description(self):
        with pytest.raises(ValidationError):
            AgentState()

    def test_tool_errors_accumulate_independently_of_other_lists(self):
        state = AgentState(task_description="task")
        state.tool_errors.append({"tool": "create_document", "error": "boom"})

        assert len(state.tool_errors) == 1
        assert state.messages == []  # unaffected


class TestPlanOutput:
    """See ADR B3 — structured-output schema for the planning phase."""

    def test_builds_from_llm_shaped_dict(self):
        plan = PlanOutput(todos=[
            {"description": "Research regulatory requirements"},
            {"description": "Create clinical summary", "dependencies": ["Research regulatory requirements"]},
        ])

        assert len(plan.todos) == 2
        assert all(isinstance(t, PlannedTodo) for t in plan.todos)
        assert plan.todos[1].dependencies == ["Research regulatory requirements"]

    def test_dependencies_default_to_empty_list(self):
        todo = PlannedTodo(description="Do the thing")
        assert todo.dependencies == []

    def test_requires_todos_list(self):
        with pytest.raises(ValidationError):
            PlanOutput()


class TestEnums:
    def test_document_type_values(self):
        assert DocumentType.REGULATORY == "regulatory"
        assert DocumentType.CLINICAL == "clinical"

    def test_knowledge_type_values(self):
        assert KnowledgeType.GLOBAL == "global"
        assert KnowledgeType.CLIENT == "client"
