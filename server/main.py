import math
import threading
import uuid
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders

app = FastAPI(title="Factory Inventory Management System")

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str
    unit_cost: float
    lead_time_days: int

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False
    # The dashboard decides between "Create PO" and "View PO" from this id, so it must
    # be populated on load, not just set client-side after creating a PO
    purchase_order_id: Optional[str] = None

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

class Task(BaseModel):
    id: str
    title: str
    priority: str
    # camelCase to match the task shape the frontend already uses for its mock tasks
    dueDate: str
    status: str

class CreateTaskRequest(BaseModel):
    title: str
    priority: str = "medium"
    dueDate: str

class RestockOrderItemRequest(BaseModel):
    sku: str
    quantity: int

class CreateRestockOrderRequest(BaseModel):
    budget: float
    items: List[RestockOrderItemRequest]

class RestockOrderItem(BaseModel):
    sku: str
    name: str
    quantity: int
    unit_cost: float
    lead_time_days: int
    line_total: float

class RestockOrder(BaseModel):
    id: str
    order_number: str
    items: List[RestockOrderItem]
    total_value: float
    budget: float
    lead_time_days: int
    order_date: str
    expected_delivery: str
    status: str

# Submitted restocking orders live in memory only and reset on server restart
restock_orders: list = []
# Sync endpoints run in a threadpool, so guard numbering + append against concurrent POSTs
restock_orders_lock = threading.Lock()

# Purchase orders start from purchase_orders.json and new ones are appended in memory;
# the lock keeps the one-PO-per-backlog-item check and the append atomic
purchase_orders_lock = threading.Lock()

# User tasks live in memory only and reset on server restart
tasks: list = []
tasks_lock = threading.Lock()
VALID_TASK_PRIORITIES = {"low", "medium", "high"}

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        po = next((po for po in purchase_orders if po["backlog_item_id"] == item["id"]), None)
        item_dict["has_purchase_order"] = po is not None
        item_dict["purchase_order_id"] = po["id"] if po else None
        result.append(item_dict)
    return result

@app.post("/api/purchase-orders", response_model=PurchaseOrder, status_code=201)
def create_purchase_order(request: CreatePurchaseOrderRequest):
    """Create a purchase order to cover a backlog item's shortage"""
    if not any(item["id"] == request.backlog_item_id for item in backlog_items):
        raise HTTPException(status_code=404, detail=f"Backlog item {request.backlog_item_id} not found")
    if not request.supplier_name.strip():
        raise HTTPException(status_code=400, detail="Supplier name is required")
    if request.quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")
    # Manual check instead of a Pydantic constraint, for the same NaN reason as restock budgets
    if not math.isfinite(request.unit_cost) or request.unit_cost <= 0:
        raise HTTPException(status_code=400, detail="Unit cost must be a positive finite number")
    try:
        datetime.strptime(request.expected_delivery_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Expected delivery date must be YYYY-MM-DD")

    with purchase_orders_lock:
        if any(po["backlog_item_id"] == request.backlog_item_id for po in purchase_orders):
            raise HTTPException(
                status_code=409,
                detail=f"Backlog item {request.backlog_item_id} already has a purchase order"
            )
        po = {
            "id": f"PO-{len(purchase_orders) + 1:04d}",
            "backlog_item_id": request.backlog_item_id,
            "supplier_name": request.supplier_name.strip(),
            "quantity": request.quantity,
            "unit_cost": request.unit_cost,
            "expected_delivery_date": request.expected_delivery_date,
            "status": "Pending",
            "created_date": datetime.now().replace(microsecond=0).isoformat(),
            "notes": request.notes
        }
        purchase_orders.append(po)
    return po

@app.get("/api/purchase-orders/{backlog_item_id}", response_model=PurchaseOrder)
def get_purchase_order_by_backlog_item(backlog_item_id: str):
    """Get the purchase order for a backlog item"""
    po = next((po for po in purchase_orders if po["backlog_item_id"] == backlog_item_id), None)
    if not po:
        raise HTTPException(status_code=404, detail=f"Purchase order for backlog item {backlog_item_id} not found")
    return po

@app.get("/api/tasks", response_model=List[Task])
def get_tasks():
    """Get user tasks, newest first"""
    return list(reversed(tasks))

@app.post("/api/tasks", response_model=Task, status_code=201)
def create_task(request: CreateTaskRequest):
    """Create a task"""
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    if request.priority not in VALID_TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail="Priority must be low, medium or high")
    try:
        datetime.strptime(request.dueDate, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Due date must be YYYY-MM-DD")

    # String ids so they never collide with the frontend's numeric mock task ids,
    # which App.vue merges into the same list and tells apart by id
    task = {
        "id": f"task-{uuid.uuid4().hex[:12]}",
        "title": title,
        "priority": request.priority,
        "dueDate": request.dueDate,
        "status": "pending"
    }
    with tasks_lock:
        tasks.append(task)
    return task

@app.patch("/api/tasks/{task_id}", response_model=Task)
def toggle_task(task_id: str):
    """Toggle a task between pending and completed"""
    with tasks_lock:
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        task["status"] = "completed" if task["status"] == "pending" else "pending"
        return task

@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str):
    """Delete a task"""
    with tasks_lock:
        index = next((i for i, t in enumerate(tasks) if t["id"] == task_id), None)
        if index is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        tasks.pop(index)
    return {"deleted": task_id}

@app.get("/api/restock-orders", response_model=List[RestockOrder])
def get_restock_orders():
    """Get submitted restocking orders, newest first"""
    return list(reversed(restock_orders))

@app.post("/api/restock-orders", response_model=RestockOrder, status_code=201)
def create_restock_order(request: CreateRestockOrderRequest):
    """Submit a restocking order for demand forecast items"""
    # Checked here rather than with a Pydantic constraint: a 422 for NaN would echo the NaN
    # back and fail JSON serialization. NaN must be rejected because comparisons against it
    # are always False, which would let any order through the budget check below.
    if not math.isfinite(request.budget) or request.budget < 0:
        raise HTTPException(status_code=400, detail="Budget must be a non-negative finite number")
    if not request.items:
        raise HTTPException(status_code=400, detail="Order must contain at least one item")

    skus = [item.sku for item in request.items]
    if len(skus) != len(set(skus)):
        raise HTTPException(status_code=400, detail="Each SKU may appear only once per order")

    forecasts_by_sku = {f["item_sku"]: f for f in demand_forecasts}
    order_items = []
    for requested in request.items:
        forecast = forecasts_by_sku.get(requested.sku)
        if not forecast:
            raise HTTPException(status_code=400, detail=f"Unknown SKU {requested.sku}")
        if requested.quantity <= 0:
            raise HTTPException(status_code=400, detail=f"Quantity for {requested.sku} must be positive")
        # Prices come from the forecast catalog, not the client, so the budget check can't be bypassed
        order_items.append({
            "sku": requested.sku,
            "name": forecast["item_name"],
            "quantity": requested.quantity,
            "unit_cost": forecast["unit_cost"],
            "lead_time_days": forecast["lead_time_days"],
            "line_total": round(requested.quantity * forecast["unit_cost"], 2)
        })

    total_value = round(sum(item["line_total"] for item in order_items), 2)
    if total_value > request.budget:
        raise HTTPException(
            status_code=400,
            detail=f"Order total {total_value} exceeds budget {request.budget}"
        )

    # The order is delivered complete, so it arrives when its slowest item does
    lead_time_days = max(item["lead_time_days"] for item in order_items)
    order_date = datetime.now().replace(microsecond=0)
    with restock_orders_lock:
        sequence = len(restock_orders) + 1
        order = {
            "id": f"restock-{sequence}",
            "order_number": f"RST-{sequence:04d}",
            "items": order_items,
            "total_value": total_value,
            "budget": request.budget,
            "lead_time_days": lead_time_days,
            "order_date": order_date.isoformat(),
            "expected_delivery": (order_date + timedelta(days=lead_time_days)).isoformat(),
            "status": "Submitted"
        }
        restock_orders.append(order)
    return order

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
