"""
Tests for restocking order API endpoints.
"""
import pytest

import main


@pytest.fixture(autouse=True)
def reset_restock_orders():
    """Clear in-memory restock orders so each test starts empty."""
    main.restock_orders.clear()
    yield
    main.restock_orders.clear()


class TestRestockOrderEndpoints:
    """Test suite for restocking order endpoints."""

    def test_demand_forecasts_include_pricing(self, client):
        """Test that forecasts expose unit cost and lead time for restocking."""
        response = client.get("/api/demand")
        assert response.status_code == 200

        for forecast in response.json():
            assert isinstance(forecast["unit_cost"], (int, float))
            assert isinstance(forecast["lead_time_days"], int)
            assert forecast["unit_cost"] > 0
            assert forecast["lead_time_days"] > 0

    def test_get_restock_orders_empty(self, client):
        """Test listing restock orders when none have been submitted."""
        response = client.get("/api/restock-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restock_order(self, client):
        """Test submitting a restock order and listing it back."""
        payload = {"budget": 100000, "items": [{"sku": "WDG-001", "quantity": 10}]}
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 201

        order = response.json()
        assert order["order_number"] == "RST-0001"
        assert order["status"] == "Submitted"
        assert order["budget"] == 100000
        assert len(order["items"]) == 1
        assert order["items"][0]["name"] == "Industrial Widget Type A"
        assert "T" in order["order_date"]
        assert "T" in order["expected_delivery"]

        list_response = client.get("/api/restock-orders")
        assert list_response.status_code == 200
        orders = list_response.json()
        assert len(orders) == 1
        assert orders[0]["id"] == order["id"]

    def test_restock_orders_newest_first(self, client):
        """Test that restock orders are listed newest first."""
        for _ in range(2):
            client.post("/api/restock-orders", json={"budget": 100000, "items": [{"sku": "GSK-203", "quantity": 1}]})

        orders = client.get("/api/restock-orders").json()
        assert [o["order_number"] for o in orders] == ["RST-0002", "RST-0001"]

    def test_restock_order_total_calculation(self, client):
        """Test that totals are computed server-side from forecast prices."""
        forecasts = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        payload = {
            "budget": 100000,
            "items": [{"sku": "WDG-001", "quantity": 10}, {"sku": "GSK-203", "quantity": 4}]
        }
        order = client.post("/api/restock-orders", json=payload).json()

        expected = 10 * forecasts["WDG-001"]["unit_cost"] + 4 * forecasts["GSK-203"]["unit_cost"]
        assert abs(order["total_value"] - expected) < 0.01
        for item in order["items"]:
            assert item["unit_cost"] == forecasts[item["sku"]]["unit_cost"]
            assert abs(item["line_total"] - item["quantity"] * item["unit_cost"]) < 0.01

    def test_restock_order_lead_time_calculation(self, client):
        """Test that order lead time is the longest item lead time."""
        forecasts = {f["item_sku"]: f for f in client.get("/api/demand").json()}
        skus = ["FLT-405", "MTR-304", "GSK-203"]
        payload = {"budget": 100000, "items": [{"sku": s, "quantity": 1} for s in skus]}
        order = client.post("/api/restock-orders", json=payload).json()

        assert order["lead_time_days"] == max(forecasts[s]["lead_time_days"] for s in skus)

    def test_restock_order_over_budget(self, client):
        """Test that an order exceeding the budget is rejected."""
        payload = {"budget": 10, "items": [{"sku": "MTR-304", "quantity": 5}]}
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()
        assert main.restock_orders == []

    def test_restock_order_unknown_sku(self, client):
        """Test that an order with an unknown SKU is rejected."""
        payload = {"budget": 100000, "items": [{"sku": "NOPE-999", "quantity": 1}]}
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 400
        assert "NOPE-999" in response.json()["detail"]

    def test_restock_order_empty_items(self, client):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restock-orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400

    def test_restock_order_zero_quantity(self, client):
        """Test that an order with a non-positive quantity is rejected."""
        payload = {"budget": 1000, "items": [{"sku": "WDG-001", "quantity": 0}]}
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 400

    @pytest.mark.parametrize("budget", ["NaN", "Infinity", "-Infinity", "-100"])
    def test_restock_order_invalid_budget(self, client, budget):
        """Test that non-finite or negative budgets are rejected."""
        # Raw body because the json module can't emit NaN/Infinity as standard JSON
        body = '{"budget": %s, "items": [{"sku": "MTR-304", "quantity": 1000}]}' % budget
        response = client.post(
            "/api/restock-orders", content=body, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()
        assert main.restock_orders == []

    def test_restock_order_duplicate_sku(self, client):
        """Test that the same SKU listed twice in one order is rejected."""
        payload = {
            "budget": 100000,
            "items": [{"sku": "WDG-001", "quantity": 1}, {"sku": "WDG-001", "quantity": 2}]
        }
        response = client.post("/api/restock-orders", json=payload)
        assert response.status_code == 400
        assert main.restock_orders == []
