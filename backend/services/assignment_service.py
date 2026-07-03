"""
Auto-assignment service — finds the best available agent for an order.

Logic:
1. Query agents where role == delivery_agent, agent_status == available,
   AND zone == pickup_zone_id.
2. For each candidate, count active (non-terminal) orders.
3. Pick the candidate with the fewest active orders (tie-break: first found).
4. If no candidates, raise NoAgentAvailableError.
"""
from __future__ import annotations
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

# Terminal statuses — agent is freed after reaching these
TERMINAL_STATUSES = {"Delivered", "Failed"}


class NoAgentAvailableError(Exception):
    """Raised when no available agent exists in the pickup zone."""


async def auto_assign_agent(
    order_id: str,
    pickup_zone_id: str,
    db: AsyncIOMotorDatabase,
) -> str:
    """
    Find the best available agent in the pickup zone.

    Returns the agent's user_id (str) if found.
    Raises NoAgentAvailableError if none available.
    """
    # Find all available agents in the zone
    candidates = []
    async for agent in db["users"].find({
        "role": "delivery_agent",
        "agent_status": "available",
        "zone": pickup_zone_id,
    }):
        agent_id = str(agent["_id"])
        # Count non-terminal (active) orders for this agent
        active_count = await db["orders"].count_documents({
            "assigned_agent_id": agent_id,
            "current_status": {"$nin": list(TERMINAL_STATUSES)},
        })
        candidates.append((active_count, agent_id))

    if not candidates:
        raise NoAgentAvailableError(
            f"No available delivery agent found in zone {pickup_zone_id}. "
            "Try assigning manually or wait for an agent to become available."
        )

    # Pick agent with fewest active orders
    candidates.sort(key=lambda x: x[0])
    best_agent_id = candidates[0][1]
    return best_agent_id


async def assign_agent_to_order(
    order_id: str,
    agent_id: str,
    db: AsyncIOMotorDatabase,
) -> None:
    """
    Persist the assignment: update order.assigned_agent_id and
    set agent.agent_status = "busy".
    Called by both auto_assign and manual assign routes.
    """
    await db["orders"].update_one(
        {"_id": ObjectId(order_id)},
        {"$set": {"assigned_agent_id": agent_id}},
    )
    await db["users"].update_one(
        {"_id": ObjectId(agent_id)},
        {"$set": {"agent_status": "busy"}},
    )


async def release_agent(agent_id: str, db: AsyncIOMotorDatabase) -> None:
    """
    Set agent back to 'available' after terminal status (Delivered/Failed).
    """
    await db["users"].update_one(
        {"_id": ObjectId(agent_id)},
        {"$set": {"agent_status": "available"}},
    )
