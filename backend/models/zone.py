from typing import List, Optional
from pydantic import BaseModel, Field
from backend.models.base import MongoBase, PyObjectId


# ── DB document ───────────────────────────────────────────────────────────────
class ZoneInDB(MongoBase):
    name: str
    areas: List[str]   # list of pincodes or locality name strings


# ── Request / Response schemas ─────────────────────────────────────────────────
class CreateZoneRequest(BaseModel):
    name: str
    areas: List[str] = Field(..., min_length=1)


class UpdateZoneRequest(BaseModel):
    name: Optional[str] = None
    areas: Optional[List[str]] = None


class ZoneResponse(BaseModel):
    id: Optional[PyObjectId] = Field(default=None, alias="_id")
    name: str
    areas: List[str]

    model_config = {"populate_by_name": True}
