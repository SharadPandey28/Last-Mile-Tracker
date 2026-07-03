"""
Admin routes — zone CRUD, rate card CRUD, COD surcharge CRUD,
agent creation, all-orders view with filters, status override, manual assign.
All endpoints require admin role.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.database import get_db
from backend.dependencies import require_roles
from backend.models.user import CreateAgentRequest, UserPublic, UserInDB
from backend.models.zone import CreateZoneRequest, UpdateZoneRequest, ZoneResponse
from backend.models.rate_card import (
    CreateRateCardRequest, UpdateRateCardRequest, RateCardResponse,
    CreateCODSurchargeRequest, CODSurchargeResponse,
)
from backend.models.order import (
    AdminStatusOverrideRequest, ManualAssignRequest, OrderResponse,
)
from backend.services.auth_service import hash_password
from backend.services.order_service import update_order_status, InvalidTransitionError, OrderNotFoundError
from backend.services.assignment_service import (
    assign_agent_to_order, auto_assign_agent, NoAgentAvailableError
)

router = APIRouter(prefix="/admin", tags=["Admin"])

_admin_dep = Depends(require_roles("admin"))


def _oid(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid ID format: {id_str}")


def _serialize(doc: dict) -> dict:
    """Convert ObjectId fields to strings for JSON serialization."""
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


# ─────────────────────────────────────────────────────────────────────────────
# Zones
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/zones", status_code=201)
async def create_zone(
    body: CreateZoneRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    doc = {"name": body.name, "areas": body.areas}
    result = await db["zones"].insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


@router.get("/zones", response_model=List[ZoneResponse])
async def list_zones(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    zones = []
    async for z in db["zones"].find({}):
        z["_id"] = str(z["_id"])
        zones.append(z)
    return zones


@router.get("/zones/{zone_id}")
async def get_zone(
    zone_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    z = await db["zones"].find_one({"_id": _oid(zone_id)})
    if not z:
        raise HTTPException(404, "Zone not found")
    return _serialize(z)


@router.put("/zones/{zone_id}")
async def update_zone(
    zone_id: str,
    body: UpdateZoneRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    result = await db["zones"].update_one({"_id": _oid(zone_id)}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Zone not found")
    z = await db["zones"].find_one({"_id": _oid(zone_id)})
    return _serialize(z)


@router.delete("/zones/{zone_id}", status_code=204)
async def delete_zone(
    zone_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    result = await db["zones"].delete_one({"_id": _oid(zone_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Zone not found")


# ─────────────────────────────────────────────────────────────────────────────
# Rate Cards
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/rate-cards", status_code=201)
async def create_rate_card(
    body: CreateRateCardRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _admin_dep,
):
    doc = body.model_dump()
    doc["updated_by"] = str(current_user.id) if current_user.id else None
    doc["updated_at"] = datetime.now(timezone.utc)
    result = await db["rate_cards"].insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    return doc


@router.get("/rate-cards")
async def list_rate_cards(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    cards = []
    async for c in db["rate_cards"].find({}):
        c["_id"] = str(c["_id"])
        cards.append(c)
    return cards


@router.put("/rate-cards/{card_id}")
async def update_rate_card(
    card_id: str,
    body: UpdateRateCardRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _admin_dep,
):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updates["updated_by"] = str(current_user.id) if current_user.id else None
    updates["updated_at"] = datetime.now(timezone.utc)
    result = await db["rate_cards"].update_one({"_id": _oid(card_id)}, {"$set": updates})
    if result.matched_count == 0:
        raise HTTPException(404, "Rate card not found")
    c = await db["rate_cards"].find_one({"_id": _oid(card_id)})
    return _serialize(c)


@router.delete("/rate-cards/{card_id}", status_code=204)
async def delete_rate_card(
    card_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    result = await db["rate_cards"].delete_one({"_id": _oid(card_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Rate card not found")


# ─────────────────────────────────────────────────────────────────────────────
# COD Surcharge Config
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/cod-surcharge", status_code=201)
async def upsert_cod_surcharge(
    body: CreateCODSurchargeRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    """Upsert COD surcharge for a given order type."""
    doc = {
        "order_type": body.order_type,
        "surcharge_amount": body.surcharge_amount,
        "updated_at": datetime.now(timezone.utc),
    }
    await db["cod_surcharge_config"].update_one(
        {"order_type": body.order_type},
        {"$set": doc},
        upsert=True,
    )
    result = await db["cod_surcharge_config"].find_one({"order_type": body.order_type})
    return _serialize(result)


@router.get("/cod-surcharge")
async def list_cod_surcharges(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    configs = []
    async for c in db["cod_surcharge_config"].find({}):
        c["_id"] = str(c["_id"])
        configs.append(c)
    return configs


@router.delete("/cod-surcharge/{order_type}", status_code=204)
async def delete_cod_surcharge(
    order_type: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    result = await db["cod_surcharge_config"].delete_one({"order_type": order_type})
    if result.deleted_count == 0:
        raise HTTPException(404, "Surcharge config not found")


# ─────────────────────────────────────────────────────────────────────────────
# Agent accounts (admin creates only)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/agents", status_code=201)
async def create_agent(
    body: CreateAgentRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    existing = await db["users"].find_one({"email": body.email})
    if existing:
        raise HTTPException(400, "Email already in use")
    doc = {
        "name": body.name,
        "email": body.email,
        "password_hash": hash_password(body.password),
        "role": "delivery_agent",
        "zone": body.zone,
        "agent_status": "available",
        "created_at": datetime.now(timezone.utc),
    }
    result = await db["users"].insert_one(doc)
    doc["_id"] = str(result.inserted_id)
    doc.pop("password_hash", None)
    return doc


@router.get("/agents")
async def list_agents(
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    agents = []
    async for a in db["users"].find({"role": "delivery_agent"}):
        a["_id"] = str(a["_id"])
        a.pop("password_hash", None)
        agents.append(a)
    return agents


# ─────────────────────────────────────────────────────────────────────────────
# All orders (with filters)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/orders")
async def list_all_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    zone: Optional[str] = Query(None),
    agent: Optional[str] = Query(None),
    db: AsyncIOMotorDatabase = Depends(get_db),
    _: UserInDB = _admin_dep,
):
    query: dict = {}
    if status_filter:
        query["current_status"] = status_filter
    if zone:
        query["$or"] = [{"pickup_zone_id": zone}, {"drop_zone_id": zone}]
    if agent:
        query["assigned_agent_id"] = agent

    orders = []
    async for o in db["orders"].find(query, sort=[("created_at", -1)]):
        o["_id"] = str(o["_id"])
        orders.append(o)
    return orders


# ─────────────────────────────────────────────────────────────────────────────
# Status override
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/orders/{order_id}/status")
async def override_order_status(
    order_id: str,
    body: AdminStatusOverrideRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _admin_dep,
):
    try:
        updated = await update_order_status(
            order_id=order_id,
            new_status=body.new_status,
            actor_id=str(current_user.id),
            actor_role="admin",
            db=db,
            notes=body.notes,
        )
        return _serialize(updated)
    except OrderNotFoundError as e:
        raise HTTPException(404, str(e))
    except InvalidTransitionError as e:
        raise HTTPException(400, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Manual agent assignment
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/orders/{order_id}/assign")
async def manual_assign_agent(
    order_id: str,
    body: ManualAssignRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
    current_user: UserInDB = _admin_dep,
):
    order = await db["orders"].find_one({"_id": _oid(order_id)})
    if not order:
        raise HTTPException(404, "Order not found")

    agent = await db["users"].find_one({"_id": _oid(body.agent_id), "role": "delivery_agent"})
    if not agent:
        raise HTTPException(404, "Agent not found")

    await assign_agent_to_order(order_id, body.agent_id, db)

    # Transition to Assigned if currently Created or Rescheduled
    current_status = order.get("current_status", "")
    if current_status in ("Created", "Rescheduled"):
        try:
            await update_order_status(
                order_id=order_id,
                new_status="Assigned",
                actor_id=str(current_user.id),
                actor_role="admin",
                db=db,
                notes=f"Manually assigned to agent {body.agent_id}",
            )
        except InvalidTransitionError:
            pass  # If status is already Assigned, skip

    updated = await db["orders"].find_one({"_id": _oid(order_id)})
    return _serialize(updated)
