from enum import Enum
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from backend.models.base import MongoBase, PyObjectId


class OrderStatus(str, Enum):
    Created = "Created"
    Assigned = "Assigned"
    PickedUp = "Picked Up"
    InTransit = "In Transit"
    OutForDelivery = "Out for Delivery"
    Delivered = "Delivered"
    Failed = "Failed"
    Rescheduled = "Rescheduled"


class PaymentType(str, Enum):
    COD = "COD"
    prepaid = "prepaid"


class OrderType(str, Enum):
    B2B = "B2B"
    B2C = "B2C"


class Dimensions(BaseModel):
    l: float   # length in cm
    b: float   # breadth in cm
    h: float   # height in cm


# ── DB document ───────────────────────────────────────────────────────────────
class OrderInDB(MongoBase):
    customer_id: str
    created_by: str
    pickup_address: str
    drop_address: str
    pickup_zone_id: Optional[str] = None
    drop_zone_id: Optional[str] = None
    dimensions: Dimensions
    actual_weight: float
    volumetric_weight: Optional[float] = None
    billable_weight: Optional[float] = None
    order_type: OrderType
    payment_type: PaymentType
    calculated_charge: Optional[float] = None
    current_status: OrderStatus = OrderStatus.Created
    assigned_agent_id: Optional[str] = None
    reschedule_date: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Request / Response schemas ─────────────────────────────────────────────────
class CalculateChargeRequest(BaseModel):
    pickup_address: str
    drop_address: str
    dimensions: Dimensions
    actual_weight: float
    order_type: OrderType
    payment_type: PaymentType


class PlaceOrderRequest(BaseModel):
    pickup_address: str
    drop_address: str
    dimensions: Dimensions
    actual_weight: float
    order_type: OrderType
    payment_type: PaymentType


class ChargeBreakdown(BaseModel):
    pickup_zone_id: str
    pickup_zone_name: str
    drop_zone_id: str
    drop_zone_name: str
    zone_relation: str
    volumetric_weight: float
    billable_weight: float
    base_rate: float
    per_kg_rate: float
    base_charge: float
    cod_surcharge: float
    final_charge: float


class RescheduleRequest(BaseModel):
    reschedule_date: datetime


class AdminStatusOverrideRequest(BaseModel):
    new_status: OrderStatus
    notes: Optional[str] = None


class AgentStatusUpdateRequest(BaseModel):
    new_status: OrderStatus
    notes: Optional[str] = None


class ManualAssignRequest(BaseModel):
    agent_id: str


class OrderResponse(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    customer_id: str
    created_by: str
    pickup_address: str
    drop_address: str
    pickup_zone_id: Optional[str] = None
    drop_zone_id: Optional[str] = None
    dimensions: Dimensions
    actual_weight: float
    volumetric_weight: Optional[float] = None
    billable_weight: Optional[float] = None
    order_type: OrderType
    payment_type: PaymentType
    calculated_charge: Optional[float] = None
    current_status: OrderStatus
    assigned_agent_id: Optional[str] = None
    reschedule_date: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"populate_by_name": True}
