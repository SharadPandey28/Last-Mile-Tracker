"""
Order lifecycle service — status state machine with append-only tracking.

Valid transitions (enforced strictly):
  Created       → Assigned
  Assigned      → Picked Up
  Picked Up     → In Transit | Failed
  In Transit    → Out for Delivery | Failed
  Out for Delivery → Delivered | Failed
  Failed        → Rescheduled
  Rescheduled   → Assigned

On every transition:
  1. Validate the transition is allowed
  2. Update orders.current_status
  3. INSERT a new tracking_history document (never update/delete)
  4. If terminal status (Delivered / Failed): free the agent
  5. Trigger email notification to the customer
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.services import notification_service
from backend.services.assignment_service import release_agent

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# State machine definition
# ─────────────────────────────────────────────────────────────────────────────
VALID_TRANSITIONS: dict[str, set[str]] = {
    "Created":          {"Assigned"},
    "Assigned":         {"Picked Up"},
    "Picked Up":        {"In Transit", "Failed"},
    "In Transit":       {"Out for Delivery", "Failed"},
    "Out for Delivery": {"Delivered", "Failed"},
    "Delivered":        set(),          # terminal
    "Failed":           {"Rescheduled"},
    "Rescheduled":      {"Assigned"},
}

TERMINAL_STATUSES = {"Delivered", "Failed"}


class InvalidTransitionError(Exception):
    pass


class OrderNotFoundError(Exception):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Core update function
# ─────────────────────────────────────────────────────────────────────────────
async def update_order_status(
    order_id: str,
    new_status: str,
    actor_id: str,
    actor_role: str,
    db: AsyncIOMotorDatabase,
    notes: str | None = None,
) -> dict:
    """
    Transition an order to a new status.

    Returns the updated order document.
    Raises InvalidTransitionError for illegal transitions.
    Raises OrderNotFoundError if the order does not exist.
    """
    order = await db["orders"].find_one({"_id": ObjectId(order_id)})
    if order is None:
        raise OrderNotFoundError(f"Order {order_id} not found")

    current_status = order["current_status"]

    # Validate transition
    allowed = VALID_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from '{current_status}' to '{new_status}'. "
            f"Allowed next statuses: {sorted(allowed) or ['(none — terminal)']}"
        )

    # 1. Update order status
    await db["orders"].update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"current_status": new_status}},
    )

    # 2. Append tracking history (NEVER mutate existing documents)
    tracking_doc = {
        "order_id": order_id,
        "status": new_status,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "timestamp": datetime.now(timezone.utc),
        "notes": notes,
    }
    await db["tracking_history"].insert_one(tracking_doc)

    # 3. Free agent on terminal status
    if new_status in TERMINAL_STATUSES:
        agent_id = order.get("assigned_agent_id")
        if agent_id:
            await release_agent(agent_id, db)
            logger.info("Agent %s released (order %s → %s)", agent_id, order_id, new_status)

    # 4. Email notification — get customer email
    customer_id = order.get("customer_id")
    if customer_id:
        try:
            customer = await db["users"].find_one({"_id": ObjectId(customer_id)})
            if customer:
                customer_email = customer.get("email", "")
                if new_status == "Failed":
                    notification_service.send_failed_delivery_email(
                        customer_email, order_id, notes
                    )
                else:
                    notification_service.send_status_update_email(
                        customer_email, order_id, new_status, notes
                    )
        except Exception as e:
            logger.error("Notification error for order %s: %s", order_id, e)

    # Return updated order
    updated_order = await db["orders"].find_one({"_id": ObjectId(order_id)})
    return updated_order


async def get_tracking_history(
    order_id: str,
    db: AsyncIOMotorDatabase,
) -> list[dict]:
    """
    Return all tracking events for an order, sorted chronologically.
    (Read-only — never modifies the collection.)
    """
    events = []
    async for doc in db["tracking_history"].find(
        {"order_id": order_id},
        sort=[("timestamp", 1)],
    ):
        doc["_id"] = str(doc["_id"])
        events.append(doc)
    return events
