"""
Tests for purchase order and task API endpoints.
"""
import pytest

import main


@pytest.fixture(autouse=True)
def reset_in_memory_state():
    """Restore purchase orders and tasks so each test starts from the loaded data."""
    original_pos = list(main.purchase_orders)
    main.tasks.clear()
    yield
    # Mutate in place: main.purchase_orders is the same list object mock_data loaded
    main.purchase_orders[:] = original_pos
    main.tasks.clear()


def po_payload(backlog_item_id="1", **overrides):
    payload = {
        "backlog_item_id": backlog_item_id,
        "supplier_name": "Acme Supply",
        "quantity": 350,
        "unit_cost": 12.5,
        "expected_delivery_date": "2026-12-01",
        "notes": "Rush order",
    }
    payload.update(overrides)
    return payload


class TestPurchaseOrderEndpoints:
    """Test suite for purchase order endpoints."""

    def test_create_purchase_order(self, client):
        """Test creating a purchase order for a backlog item."""
        response = client.post("/api/purchase-orders", json=po_payload())
        assert response.status_code == 201

        po = response.json()
        assert po["id"].startswith("PO-")
        assert po["backlog_item_id"] == "1"
        assert po["supplier_name"] == "Acme Supply"
        assert po["quantity"] == 350
        assert po["status"] == "Pending"
        assert "T" in po["created_date"]

    def test_get_purchase_order_by_backlog_item(self, client):
        """Test fetching a created purchase order by its backlog item."""
        created = client.post("/api/purchase-orders", json=po_payload()).json()

        response = client.get("/api/purchase-orders/1")
        assert response.status_code == 200
        assert response.json() == created

    def test_get_nonexistent_purchase_order(self, client):
        """Test fetching a purchase order for a backlog item without one."""
        response = client.get("/api/purchase-orders/1")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_backlog_reflects_purchase_order(self, client):
        """Test that backlog items expose the PO id after creation."""
        before = {b["id"]: b for b in client.get("/api/backlog").json()}
        assert before["1"]["purchase_order_id"] is None
        assert before["1"]["has_purchase_order"] is False

        created = client.post("/api/purchase-orders", json=po_payload()).json()

        after = {b["id"]: b for b in client.get("/api/backlog").json()}
        assert after["1"]["purchase_order_id"] == created["id"]
        assert after["1"]["has_purchase_order"] is True
        assert after["2"]["purchase_order_id"] is None

    def test_duplicate_purchase_order_rejected(self, client):
        """Test that a backlog item can only have one purchase order."""
        assert client.post("/api/purchase-orders", json=po_payload()).status_code == 201
        response = client.post("/api/purchase-orders", json=po_payload())
        assert response.status_code == 409

    def test_purchase_order_unknown_backlog_item(self, client):
        """Test creating a PO for a backlog item that doesn't exist."""
        response = client.post("/api/purchase-orders", json=po_payload("nonexistent-999"))
        assert response.status_code == 404

    @pytest.mark.parametrize("overrides", [
        {"supplier_name": "   "},
        {"quantity": 0},
        {"unit_cost": 0},
        {"unit_cost": -5},
        {"expected_delivery_date": "12/01/2026"},
    ])
    def test_purchase_order_invalid_input(self, client, overrides):
        """Test that invalid purchase order fields are rejected."""
        response = client.post("/api/purchase-orders", json=po_payload(**overrides))
        assert response.status_code == 400
        assert "detail" in response.json()


class TestTaskEndpoints:
    """Test suite for task endpoints."""

    def test_get_tasks_empty(self, client):
        """Test listing tasks when none exist."""
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_task(self, client):
        """Test creating a task and listing it back."""
        payload = {"title": "  Check stock  ", "priority": "high", "dueDate": "2026-11-10"}
        response = client.post("/api/tasks", json=payload)
        assert response.status_code == 201

        task = response.json()
        assert isinstance(task["id"], str)
        assert task["title"] == "Check stock"
        assert task["priority"] == "high"
        assert task["dueDate"] == "2026-11-10"
        assert task["status"] == "pending"

        assert client.get("/api/tasks").json() == [task]

    def test_tasks_listed_newest_first(self, client):
        """Test that newer tasks come first."""
        first = client.post("/api/tasks", json={"title": "A", "dueDate": "2026-11-10"}).json()
        second = client.post("/api/tasks", json={"title": "B", "dueDate": "2026-11-11"}).json()
        ids = [t["id"] for t in client.get("/api/tasks").json()]
        assert ids == [second["id"], first["id"]]

    def test_toggle_task(self, client):
        """Test toggling a task between pending and completed."""
        task = client.post("/api/tasks", json={"title": "A", "dueDate": "2026-11-10"}).json()

        response = client.patch(f"/api/tasks/{task['id']}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

        response = client.patch(f"/api/tasks/{task['id']}")
        assert response.json()["status"] == "pending"

    def test_delete_task(self, client):
        """Test deleting a task."""
        task = client.post("/api/tasks", json={"title": "A", "dueDate": "2026-11-10"}).json()

        response = client.delete(f"/api/tasks/{task['id']}")
        assert response.status_code == 200
        assert client.get("/api/tasks").json() == []

    def test_toggle_and_delete_nonexistent_task(self, client):
        """Test 404 handling for unknown task ids."""
        assert client.patch("/api/tasks/nonexistent-999").status_code == 404
        assert client.delete("/api/tasks/nonexistent-999").status_code == 404

    @pytest.mark.parametrize("payload", [
        {"title": "   ", "dueDate": "2026-11-10"},
        {"title": "A", "priority": "urgent", "dueDate": "2026-11-10"},
        {"title": "A", "dueDate": "next week"},
    ])
    def test_create_task_invalid_input(self, client, payload):
        """Test that invalid task fields are rejected."""
        response = client.post("/api/tasks", json=payload)
        assert response.status_code == 400
