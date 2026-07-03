from enum import Enum
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from backend.models.base import MongoBase, PyObjectId


class OrderType(str, Enum):
    B2B = "B2B"
    B2C = "B2C"


class ZoneRelation(str, Enum):
    intra = "intra"
    inter = "inter"


# ── DB documents ───────────────────────────────────────────────────────────────
class RateCardInDB(MongoBase):
    order_type: OrderType
    zone_relation: ZoneRelation
    from_zone_id: str
    to_zone_id: str          # same as from_zone_id for intra
    base_rate: float
    per_kg_rate: float
    updated_by: Optional[str] = None   # admin user id
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CODSurchargeInDB(MongoBase):
    order_type: OrderType
    surcharge_amount: float
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Request / Response schemas ─────────────────────────────────────────────────
class CreateRateCardRequest(BaseModel):
    order_type: OrderType
    zone_relation: ZoneRelation
    from_zone_id: str
    to_zone_id: str
    base_rate: float
    per_kg_rate: float


class UpdateRateCardRequest(BaseModel):
    base_rate: Optional[float] = None
    per_kg_rate: Optional[float] = None


class RateCardResponse(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    order_type: OrderType
    zone_relation: ZoneRelation
    from_zone_id: str
    to_zone_id: str
    base_rate: float
    per_kg_rate: float
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None

    model_config = {"populate_by_name": True}


class CreateCODSurchargeRequest(BaseModel):
    order_type: OrderType
    surcharge_amount: float


class CODSurchargeResponse(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    order_type: OrderType
    surcharge_amount: float
    updated_at: Optional[datetime] = None

    model_config = {"populate_by_name": True}
