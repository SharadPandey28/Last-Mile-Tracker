"""
Rate Calculation Engine — ISOLATED, testable module.

This module has NO dependency on FastAPI. It accepts the Motor DB handle as a
parameter, making it fully unit-testable with a mock DB.

Public API:
    calculate_charge(pickup_address, drop_address, dimensions, actual_weight,
                     order_type, payment_type, db) -> ChargeBreakdown
"""
from __future__ import annotations

from dataclasses import dataclass
from motor.motor_asyncio import AsyncIOMotorDatabase


# ─────────────────────────────────────────────────────────────────────────────
# Output type
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ChargeBreakdown:
    pickup_zone_id: str
    pickup_zone_name: str
    drop_zone_id: str
    drop_zone_name: str
    zone_relation: str          # "intra" | "inter"
    volumetric_weight: float
    billable_weight: float
    base_rate: float
    per_kg_rate: float
    base_charge: float
    cod_surcharge: float
    final_charge: float


# ─────────────────────────────────────────────────────────────────────────────
# Custom exceptions
# ─────────────────────────────────────────────────────────────────────────────
class ZoneNotFoundError(Exception):
    """Raised when an address cannot be matched to any zone."""


class RateCardNotFoundError(Exception):
    """Raised when no rate card matches the zone pair and order type."""


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _detect_zone(address: str, db: AsyncIOMotorDatabase) -> dict:
    """
    Detect the zone for an address by checking whether any area string
    (pincode or locality name) in the zones collection is contained
    within the address string (case-insensitive).

    Returns the first matching zone document.
    Raises ZoneNotFoundError if no match is found.
    """
    address_lower = address.lower()
    async for zone in db["zones"].find({}):
        for area in zone.get("areas", []):
            if area.lower() in address_lower:
                return zone
    raise ZoneNotFoundError(
        f"No zone found matching address: '{address}'. "
        "Ensure the address contains a recognizable pincode or locality name."
    )


def _compute_volumetric_weight(l: float, b: float, h: float) -> float:
    """Standard volumetric weight: (L × B × H) / 5000."""
    return (l * b * h) / 5000.0


# ─────────────────────────────────────────────────────────────────────────────
# Main public function
# ─────────────────────────────────────────────────────────────────────────────
async def calculate_charge(
    pickup_address: str,
    drop_address: str,
    dimensions: dict,          # {"l": float, "b": float, "h": float}
    actual_weight: float,
    order_type: str,           # "B2B" | "B2C"
    payment_type: str,         # "COD" | "prepaid"
    db: AsyncIOMotorDatabase,
) -> ChargeBreakdown:
    """
    Calculate the delivery charge for an order.

    Steps:
    1. Detect pickup and drop zones by matching address strings against zones.areas
    2. Compute volumetric weight = (L × B × H) / 5000
    3. billable_weight = max(actual_weight, volumetric_weight)
    4. Determine zone_relation: "intra" if same zone, else "inter"
    5. Fetch matching rate_card from DB
    6. base_charge = base_rate + (billable_weight × per_kg_rate)
    7. Add COD surcharge if payment_type == "COD"
    8. Return full ChargeBreakdown

    All rates come from DB — nothing is hardcoded here.
    """
    # Step 1: Zone detection
    pickup_zone = await _detect_zone(pickup_address, db)
    drop_zone = await _detect_zone(drop_address, db)

    pickup_zone_id = str(pickup_zone["_id"])
    drop_zone_id = str(drop_zone["_id"])
    pickup_zone_name = pickup_zone.get("name", "")
    drop_zone_name = drop_zone.get("name", "")

    # Step 2: Volumetric weight
    l = dimensions.get("l", 0)
    b = dimensions.get("b", 0)
    h = dimensions.get("h", 0)
    volumetric_weight = _compute_volumetric_weight(l, b, h)

    # Step 3: Billable weight
    billable_weight = max(actual_weight, volumetric_weight)

    # Step 4: Zone relation
    zone_relation = "intra" if pickup_zone_id == drop_zone_id else "inter"

    # Step 5: Fetch rate card
    rate_card = await db["rate_cards"].find_one({
        "order_type": order_type,
        "zone_relation": zone_relation,
        "from_zone_id": pickup_zone_id,
        "to_zone_id": drop_zone_id,
    })

    # For inter-zone, also try the reverse direction (symmetric rates)
    if rate_card is None and zone_relation == "inter":
        rate_card = await db["rate_cards"].find_one({
            "order_type": order_type,
            "zone_relation": zone_relation,
            "from_zone_id": drop_zone_id,
            "to_zone_id": pickup_zone_id,
        })

    if rate_card is None:
        raise RateCardNotFoundError(
            f"No rate card found for order_type={order_type}, "
            f"zone_relation={zone_relation}, "
            f"from_zone={pickup_zone_id}, to_zone={drop_zone_id}"
        )

    base_rate = float(rate_card["base_rate"])
    per_kg_rate = float(rate_card["per_kg_rate"])

    # Step 6: Base charge
    base_charge = base_rate + (billable_weight * per_kg_rate)

    # Step 7: COD surcharge
    cod_surcharge = 0.0
    if payment_type == "COD":
        surcharge_doc = await db["cod_surcharge_config"].find_one(
            {"order_type": order_type}
        )
        if surcharge_doc:
            cod_surcharge = float(surcharge_doc.get("surcharge_amount", 0.0))

    # Step 8: Final charge
    final_charge = base_charge + cod_surcharge

    return ChargeBreakdown(
        pickup_zone_id=pickup_zone_id,
        pickup_zone_name=pickup_zone_name,
        drop_zone_id=drop_zone_id,
        drop_zone_name=drop_zone_name,
        zone_relation=zone_relation,
        volumetric_weight=round(volumetric_weight, 3),
        billable_weight=round(billable_weight, 3),
        base_rate=base_rate,
        per_kg_rate=per_kg_rate,
        base_charge=round(base_charge, 2),
        cod_surcharge=cod_surcharge,
        final_charge=round(final_charge, 2),
    )
