from enum import Enum
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel, EmailStr, Field
from backend.models.base import MongoBase, PyObjectId


class UserRole(str, Enum):
    customer = "customer"
    delivery_agent = "delivery_agent"
    admin = "admin"


class AgentStatus(str, Enum):
    available = "available"
    busy = "busy"


# ── DB document ──────────────────────────────────────────────────────────────
class UserInDB(MongoBase):
    name: str
    email: str
    password_hash: str
    role: UserRole
    zone: Optional[str] = None              # agent's assigned zone id
    agent_status: Optional[AgentStatus] = None  # agents only
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── Request / Response schemas ────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str
    name: str


class CreateAgentRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    zone: str   # zone _id string


class UserPublic(BaseModel):
    """Safe user representation (no password hash)."""
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str
    email: str
    role: UserRole
    zone: Optional[str] = None
    agent_status: Optional[AgentStatus] = None
    created_at: Optional[datetime] = None

    model_config = {"populate_by_name": True}
