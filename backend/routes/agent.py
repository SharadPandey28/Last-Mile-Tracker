"""
Agent routes — view assigned orders, update order status.
Agents can only move orders through their permitted transitions.
"""
from __future__ import annotations

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.database import get_db
from backend.dependencies import require_roles
from backend.models.user import UserInDB
from backend.models.order import AgentStatusUpdateRequest
from backend.services.order_service import (
    update_order_status, InvalidTransitionError, OrderNotFoundError
)

router = APIRouter(prefix="/agent", tags=["Agent"])

_agent_dep = Depends(require_roles("delivery_agent", "admin"))

# Statuses an agent is allowed to set
AGENT_ALLOWED_STATUSES = {"Picked Up", "In Transit", "Out for Delivery", "Delivered", "Failed"}


def _serialize(doc: dict) -> dict:
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def _oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(400, f"Invalid ID: {id_str}")


@router.get("/orders")
async def get_my_assigned_orders(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _agent_dep,
):
    """Return all orders currently assigned to this agent."""
    agent_id = str(current_user.id)
    orders = []
    async for o in db["orders"].find(
        {"assigned_agent_id": agent_id},
        sort=[("created_at", -1)],
    ):
        o["_id"] = str(o["_id"])
        orders.append(o)
    return orders


@router.patch("/orders/{order_id}/status")
async def update_order_status_agent(
    order_id: str,
    body: AgentStatusUpdateRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _agent_dep,
):
    """Update order status. Only statuses within AGENT_ALLOWED_STATUSES are permitted."""
    # Verify this order is assigned to the requesting agent
    order = await db["orders"].find_one({"_id": _oid(order_id)})
    if not order:
        raise HTTPException(404, "Order not found")

    if order.get("assigned_agent_id") != str(current_user.id) and current_user.role != "admin":
        raise HTTPException(403, "This order is not assigned to you")

    if body.new_status.value not in AGENT_ALLOWED_STATUSES:
        raise HTTPException(
            400,
            f"Agents cannot set status to '{body.new_status.value}'. "
            f"Allowed: {sorted(AGENT_ALLOWED_STATUSES)}",
        )

    try:
        updated = await update_order_status(
            order_id=order_id,
            new_status=body.new_status.value,
            actor_id=str(current_user.id),
            actor_role="delivery_agent",
            db=db,
            notes=body.notes,
        )
        return _serialize(updated)
    except OrderNotFoundError as e:
        raise HTTPException(404, str(e))
    except InvalidTransitionError as e:
        raise HTTPException(400, str(e))


@router.get("/orders/{order_id}/tracking")
async def get_order_tracking_agent(
    order_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _agent_dep,
):
    """Return tracking history for an agent's assigned order."""
    order = await db["orders"].find_one({"_id": _oid(order_id)})
    if not order:
        raise HTTPException(404, "Order not found")
    if order.get("assigned_agent_id") != str(current_user.id) and current_user.role != "admin":
        raise HTTPException(403, "This order is not assigned to you")

    from backend.services.order_service import get_tracking_history
    return await get_tracking_history(order_id, db)
