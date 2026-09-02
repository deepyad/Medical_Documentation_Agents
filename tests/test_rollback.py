"""Unit tests for src/rollback.py — RollbackManager, RollbackAPI, and rollback_group (ADR E2)."""
import pytest

from src.models import TaskStatus
from src.rollback import InMemoryRollbackStorage, RollbackAPI, RollbackManager


@pytest.fixture
def manager():
    return RollbackManager(InMemoryRollbackStorage())


@pytest.fixture
def api(manager):
    return RollbackAPI(manager)


class TestRollbackManager:
    def test_create_transaction_returns_retrievable_transaction(self, manager):
        transaction_id = manager.create_transaction(
            action_type="create",
            resource_id="doc_1",
            resource_type="document",
            previous_state={},
            new_state={"title": "New Doc"},
        )

        transaction = manager.get_transaction(transaction_id)

        assert transaction is not None
        assert transaction.transaction_id == transaction_id
        assert transaction.action_type == "create"
        assert transaction.resource_id == "doc_1"
        assert transaction.status == TaskStatus.COMPLETED

    def test_rollback_marks_transaction_rolled_back_and_returns_previous_state(self, manager):
        transaction_id = manager.create_transaction(
            action_type="update",
            resource_id="doc_1",
            resource_type="document",
            previous_state={"title": "Old Title"},
            new_state={"title": "New Title"},
        )

        result = manager.rollback(transaction_id)

        assert result["success"] is True
        assert result["previous_state"] == {"title": "Old Title"}
        assert manager.get_transaction(transaction_id).status == TaskStatus.ROLLED_BACK

    def test_rollback_unknown_transaction_fails_cleanly(self, manager):
        result = manager.rollback("does-not-exist")

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_list_transactions_filters_by_client_id(self, manager):
        manager.create_transaction("create", "doc_1", "document", {}, {}, client_id="client_a")
        manager.create_transaction("create", "doc_2", "document", {}, {}, client_id="client_b")

        results = manager.list_transactions(client_id="client_a")

        assert len(results) == 1
        assert results[0].resource_id == "doc_1"

    def test_list_transactions_newest_first(self, manager):
        first = manager.create_transaction("create", "doc_1", "document", {}, {})
        second = manager.create_transaction("create", "doc_2", "document", {}, {})

        results = manager.list_transactions()

        assert [t.transaction_id for t in results] == [second, first]


class TestRollbackGroup:
    """ADR E2: batch rollback via caller-supplied transaction_ids, not a stored group_id."""

    def test_rolls_back_all_transactions_in_reverse_order(self, manager):
        ids = [
            manager.create_transaction("create", f"doc_{i}", "document", {}, {"n": i})
            for i in range(3)
        ]

        result = manager.rollback_group(ids)

        assert result["success"] is True
        assert result["failed"] is None
        assert len(result["rolled_back"]) == 3
        # Rolled back in reverse creation order
        assert [r["resource_id"] for r in result["rolled_back"]] == ["doc_2", "doc_1", "doc_0"]
        for transaction_id in ids:
            assert manager.get_transaction(transaction_id).status == TaskStatus.ROLLED_BACK

    def test_stops_at_first_failure_without_continuing(self, manager):
        good_id = manager.create_transaction("create", "doc_0", "document", {}, {})
        bad_id = "does-not-exist"

        result = manager.rollback_group([good_id, bad_id])

        assert result["success"] is False
        assert result["failed"]["error"]
        # good_id was never reached because bad_id (rolled back first, in reverse order) failed
        assert result["rolled_back"] == []
        assert manager.get_transaction(good_id).status == TaskStatus.COMPLETED

    def test_empty_group_succeeds_trivially(self, manager):
        result = manager.rollback_group([])

        assert result["success"] is True
        assert result["rolled_back"] == []
        assert result["failed"] is None


class TestRollbackAPI:
    def test_execute_with_rollback_success_creates_transaction(self, api):
        store = {"doc_1": {"content": "original"}}

        def get_state(resource_id):
            return dict(store[resource_id])

        def update_state(resource_id, data):
            store[resource_id].update(data)
            return store[resource_id]

        def action():
            store["doc_1"]["content"] = "updated"
            return {"ok": True}

        result = api.execute_with_rollback(
            action_type="update",
            resource_id="doc_1",
            resource_type="document",
            action_func=action,
            get_state_func=get_state,
            update_state_func=update_state,
        )

        assert result["success"] is True
        assert result["result"] == {"ok": True}
        assert "transaction_id" in result

    def test_execute_with_rollback_failure_returns_error_without_creating_transaction(self, api, manager):
        def action():
            raise ValueError("boom")

        result = api.execute_with_rollback(
            action_type="update",
            resource_id="doc_1",
            resource_type="document",
            action_func=action,
            get_state_func=lambda resource_id: {},
            update_state_func=lambda resource_id, data: None,
        )

        assert result["success"] is False
        assert result["error"] == "boom"
        assert manager.list_transactions() == []

    def test_rollback_transaction_delegates_to_manager(self, api, manager):
        transaction_id = manager.create_transaction("create", "doc_1", "document", {}, {})

        result = api.rollback_transaction(transaction_id)

        assert result["success"] is True

    def test_rollback_group_delegates_to_manager(self, api, manager):
        ids = [manager.create_transaction("create", f"doc_{i}", "document", {}, {}) for i in range(2)]

        result = api.rollback_group(ids)

        assert result["success"] is True
        assert len(result["rolled_back"]) == 2
