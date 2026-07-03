from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from backend.models.base import MongoBase, PyObjectId


# ── DB document — APPEND ONLY ─────────────────────────────────────────────────
class TrackingHistoryInDB(MongoBase):
    """
    APPEND-ONLY collection. Every status change in an order's lifetime
    results in one new inserted document. Never update or delete.
    """
    order_id: str
    status: str
    actor_id: str
    actor_role: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: Optional[str] = None


# ── Response schema ───────────────────────────────────────────────────────────
class TrackingHistoryResponse(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    order_id: str
    status: str
    actor_id: str
    actor_role: str
    timestamp: datetime
    notes: Optional[str] = None

    model_config = {"populate_by_name": True}
