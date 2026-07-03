"""
Customer routes — calculate charge, place order, view orders,
order tracking timeline, and reschedule failed orders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.database import get_db
from backend.dependencies import require_roles
from backend.models.user import UserInDB
from backend.models.order import (
    CalculateChargeRequest, PlaceOrderRequest, RescheduleRequest,
    ChargeBreakdown,
)
from backend.services.rate_engine import (
    calculate_charge, ZoneNotFoundError, RateCardNotFoundError
)
from backend.services.order_service import (
    update_order_status, get_tracking_history, InvalidTransitionError, OrderNotFoundError
)
from backend.services.assignment_service import (
    auto_assign_agent, assign_agent_to_order, NoAgentAvailableError
)
from backend.services import notification_service

router = APIRouter(prefix="/customer", tags=["Customer"])

_customer_dep = Depends(require_roles("customer", "admin"))


def _serialize(doc: dict) -> dict:
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def _oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(400, f"Invalid ID: {id_str}")


# ─────────────────────────────────────────────────────────────────────────────
# Calculate charge (no DB write — preview only)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/orders/calculate", response_model=ChargeBreakdown)
async def calculate_order_charge(
    body: CalculateChargeRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _customer_dep,
):
    """
    Calculate delivery charge and return full breakdown.
    Does NOT create an order. Use this to show the customer the cost
    before they confirm.
    """
    try:
        breakdown = await calculate_charge(
            pickup_address=body.pickup_address,
            drop_address=body.drop_address,
            dimensions=body.dimensions.model_dump(),
            actual_weight=body.actual_weight,
            order_type=body.order_type.value,
            payment_type=body.payment_type.value,
            db=db,
        )
    except ZoneNotFoundError as e:
        raise HTTPException(422, str(e))
    except RateCardNotFoundError as e:
        raise HTTPException(422, str(e))

    return ChargeBreakdown(
        pickup_zone_id=breakdown.pickup_zone_id,
        pickup_zone_name=breakdown.pickup_zone_name,
        drop_zone_id=breakdown.drop_zone_id,
        drop_zone_name=breakdown.drop_zone_name,
        zone_relation=breakdown.zone_relation,
        volumetric_weight=breakdown.volumetric_weight,
        billable_weight=breakdown.billable_weight,
        base_rate=breakdown.base_rate,
        per_kg_rate=breakdown.per_kg_rate,
        base_charge=breakdown.base_charge,
        cod_surcharge=breakdown.cod_surcharge,
        final_charge=breakdown.final_charge,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Place / confirm order
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/orders", status_code=201)
async def place_order(
    body: PlaceOrderRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _customer_dep,
):
    """
    Confirm and place an order. Calculates charge, writes to DB,
    inserts initial tracking_history entry, and triggers auto-assignment.
    """
    try:
        breakdown = await calculate_charge(
            pickup_address=body.pickup_address,
            drop_address=body.drop_address,
            dimensions=body.dimensions.model_dump(),
            actual_weight=body.actual_weight,
            order_type=body.order_type.value,
            payment_type=body.payment_type.value,
            db=db,
        )
    except ZoneNotFoundError as e:
        raise HTTPException(422, str(e))
    except RateCardNotFoundError as e:
        raise HTTPException(422, str(e))

    customer_id = str(current_user.id)
    order_doc = {
        "customer_id": customer_id,
        "created_by": customer_id,
        "pickup_address": body.pickup_address,
        "drop_address": body.drop_address,
        "pickup_zone_id": breakdown.pickup_zone_id,
        "drop_zone_id": breakdown.drop_zone_id,
        "dimensions": body.dimensions.model_dump(),
        "actual_weight": body.actual_weight,
        "volumetric_weight": breakdown.volumetric_weight,
        "billable_weight": breakdown.billable_weight,
        "order_type": body.order_type.value,
        "payment_type": body.payment_type.value,
        "calculated_charge": breakdown.final_charge,
        "current_status": "Created",
        "assigned_agent_id": None,
        "reschedule_date": None,
        "created_at": datetime.now(timezone.utc),
    }
    result = await db["orders"].insert_one(order_doc)
    order_id = str(result.inserted_id)

    # Append initial tracking entry
    await db["tracking_history"].insert_one({
        "order_id": order_id,
        "status": "Created",
        "actor_id": customer_id,
        "actor_role": "customer",
        "timestamp": datetime.now(timezone.utc),
        "notes": "Order placed by customer",
    })

    # Auto-assign agent
    assignment_note = None
    try:
        agent_id = await auto_assign_agent(order_id, breakdown.pickup_zone_id, db)
        await assign_agent_to_order(order_id, agent_id, db)
        await update_order_status(
            order_id=order_id,
            new_status="Assigned",
            actor_id="system",
            actor_role="system",
            db=db,
            notes=f"Auto-assigned to agent {agent_id}",
        )
    except NoAgentAvailableError as e:
        assignment_note = str(e)

    order = await db["orders"].find_one({"_id": ObjectId(order_id)})
    order = _serialize(order)
    if assignment_note:
        order["_assignment_warning"] = assignment_note
    return order


# ─────────────────────────────────────────────────────────────────────────────
# View own orders
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/orders")
async def list_my_orders(
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _customer_dep,
):
    customer_id = str(current_user.id)
    orders = []
    async for o in db["orders"].find(
        {"customer_id": customer_id},
        sort=[("created_at", -1)],
    ):
        o["_id"] = str(o["_id"])
        orders.append(o)
    return orders


@router.get("/orders/{order_id}")
async def get_my_order(
    order_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _customer_dep,
):
    order = await db["orders"].find_one({"_id": _oid(order_id)})
    if not order:
        raise HTTPException(404, "Order not found")
    if order["customer_id"] != str(current_user.id) and current_user.role != "admin":
        raise HTTPException(403, "Access denied")
    return _serialize(order)


@router.get("/orders/{order_id}/tracking")
async def get_order_tracking(
    order_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _customer_dep,
):
    """Return the full tracking timeline for an order."""
    order = await db["orders"].find_one({"_id": _oid(order_id)})
    if not order:
        raise HTTPException(404, "Order not found")
    if order["customer_id"] != str(current_user.id) and current_user.role != "admin":
        raise HTTPException(403, "Access denied")
    return await get_tracking_history(order_id, db)


# ─────────────────────────────────────────────────────────────────────────────
# Reschedule failed order
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/orders/{order_id}/reschedule")
async def reschedule_order(
    order_id: str,
    body: RescheduleRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _customer_dep,
):
    order = await db["orders"].find_one({"_id": _oid(order_id)})
    if not order:
        raise HTTPException(404, "Order not found")
    if order["customer_id"] != str(current_user.id):
        raise HTTPException(403, "Access denied")
    if order["current_status"] != "Failed":
        raise HTTPException(400, "Only Failed orders can be rescheduled")

    # Update reschedule_date
    await db["orders"].update_one(
        {"_id": _oid(order_id)},
        {"$set": {"reschedule_date": body.reschedule_date}},
    )

    # Transition to Rescheduled
    try:
        await update_order_status(
            order_id=order_id,
            new_status="Rescheduled",
            actor_id=str(current_user.id),
            actor_role="customer",
            db=db,
            notes=f"Customer rescheduled for {body.reschedule_date.date()}",
        )
    except InvalidTransitionError as e:
        raise HTTPException(400, str(e))

    # Send reschedule confirmation email
    try:
        customer_email = current_user.email
        notification_service.send_reschedule_confirmation_email(
            customer_email, order_id, str(body.reschedule_date.date())
        )
    except Exception:
        pass

    # Attempt auto-assignment
    pickup_zone = order.get("pickup_zone_id", "")
    assignment_note = None
    try:
        agent_id = await auto_assign_agent(order_id, pickup_zone, db)
        await assign_agent_to_order(order_id, agent_id, db)
        await update_order_status(
            order_id=order_id,
            new_status="Assigned",
            actor_id="system",
            actor_role="system",
            db=db,
            notes=f"Auto-assigned for reschedule to agent {agent_id}",
        )
    except NoAgentAvailableError as e:
        assignment_note = str(e)

    updated = await db["orders"].find_one({"_id": _oid(order_id)})
    updated = _serialize(updated)
    if assignment_note:
        updated["_assignment_warning"] = assignment_note
    return updated
