"""
Unit tests for the rate calculation engine.

The rate_engine module takes the DB as a parameter, so we can mock it
without any real MongoDB connection — pure unit tests.

Run with:  pytest tests/test_rate_engine.py -v
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from bson import ObjectId

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.rate_engine import (
    calculate_charge, ChargeBreakdown,
    ZoneNotFoundError, RateCardNotFoundError,
    _compute_volumetric_weight,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
NORTH_ID = str(ObjectId())
SOUTH_ID = str(ObjectId())

NORTH_ZONE = {"_id": ObjectId(NORTH_ID), "name": "North Zone", "areas": ["110001", "Karol Bagh"]}
SOUTH_ZONE = {"_id": ObjectId(SOUTH_ID), "name": "South Zone", "areas": ["110017", "Hauz Khas"]}

INTRA_B2C_RATE = {
    "_id": ObjectId(),
    "order_type": "B2C",
    "zone_relation": "intra",
    "from_zone_id": NORTH_ID,
    "to_zone_id": NORTH_ID,
    "base_rate": 30.0,
    "per_kg_rate": 5.0,
}
INTER_B2C_RATE = {
    "_id": ObjectId(),
    "order_type": "B2C",
    "zone_relation": "inter",
    "from_zone_id": NORTH_ID,
    "to_zone_id": SOUTH_ID,
    "base_rate": 60.0,
    "per_kg_rate": 8.0,
}
INTER_B2B_RATE = {
    "_id": ObjectId(),
    "order_type": "B2B",
    "zone_relation": "inter",
    "from_zone_id": NORTH_ID,
    "to_zone_id": SOUTH_ID,
    "base_rate": 100.0,
    "per_kg_rate": 12.0,
}
COD_SURCHARGE_B2C = {"_id": ObjectId(), "order_type": "B2C", "surcharge_amount": 25.0}
COD_SURCHARGE_B2B = {"_id": ObjectId(), "order_type": "B2B", "surcharge_amount": 50.0}


class MockCollection:
    """A minimal async collection stub for testing."""

    def __init__(self, docs=None, find_one_result=None, find_one_func=None):
        self._docs = docs or []
        self._find_one_result = find_one_result
        self._find_one_func = find_one_func

    def find(self, _query=None):
        docs = self._docs

        async def _aiter():
            for d in docs:
                yield d

        return _aiter()

    async def find_one(self, query):
        if self._find_one_func:
            return await self._find_one_func(query)
        return self._find_one_result


class MockDB:
    """Dictionary-style DB mock that returns correct MockCollection per key."""

    def __init__(self, collections):
        self._cols = collections

    def __getitem__(self, name):
        return self._cols[name]


def make_db(zones, rate_card, cod_surcharge=None):
    """Build a mock DB that returns controlled data."""

    # zones collection — fresh iterator on every find() call
    zones_col = MockCollection(docs=zones)

    # rate_cards collection — match on all four key fields + reverse direction
    async def rate_card_find_one(query):
        if rate_card is None:
            return None
        forward_match = (
            query.get("order_type") == rate_card.get("order_type")
            and query.get("zone_relation") == rate_card.get("zone_relation")
            and query.get("from_zone_id") == rate_card.get("from_zone_id")
            and query.get("to_zone_id") == rate_card.get("to_zone_id")
        )
        reverse_match = (
            query.get("order_type") == rate_card.get("order_type")
            and query.get("zone_relation") == rate_card.get("zone_relation")
            and query.get("from_zone_id") == rate_card.get("to_zone_id")
            and query.get("to_zone_id") == rate_card.get("from_zone_id")
        )
        return rate_card if (forward_match or reverse_match) else None

    rate_cards_col = MockCollection(find_one_func=rate_card_find_one)

    # cod_surcharge_config collection
    async def cod_find_one(query):
        if cod_surcharge and cod_surcharge.get("order_type") == query.get("order_type"):
            return cod_surcharge
        return None

    cod_col = MockCollection(find_one_func=cod_find_one)

    return MockDB({
        "zones": zones_col,
        "rate_cards": rate_cards_col,
        "cod_surcharge_config": cod_col,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────────────
def test_volumetric_weight_formula():
    """Volumetric weight = (L × B × H) / 5000"""
    assert _compute_volumetric_weight(10, 10, 10) == 0.2
    assert _compute_volumetric_weight(50, 40, 30) == 12.0
    assert _compute_volumetric_weight(100, 100, 100) == 200.0


# ─────────────────────────────────────────────────────────────────────────────
# Async tests
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_intra_zone_b2c_prepaid():
    """
    Both addresses in North Zone → intra zone.
    actual_weight (5kg) > volumetric (10×10×10 / 5000 = 0.2kg) → billable = 5kg
    charge = 30 + 5 × 5 = 55
    """
    db = make_db(
        zones=[NORTH_ZONE, SOUTH_ZONE],
        rate_card=INTRA_B2C_RATE,
    )
    result = await calculate_charge(
        pickup_address="Karol Bagh, 110001",
        drop_address="Rohini 110001",
        dimensions={"l": 10, "b": 10, "h": 10},
        actual_weight=5.0,
        order_type="B2C",
        payment_type="prepaid",
        db=db,
    )
    assert result.zone_relation == "intra"
    assert result.volumetric_weight == pytest.approx(0.2, rel=1e-3)
    assert result.billable_weight == 5.0
    assert result.base_charge == pytest.approx(55.0)
    assert result.cod_surcharge == 0.0
    assert result.final_charge == pytest.approx(55.0)


@pytest.mark.asyncio
async def test_volumetric_wins_over_actual_weight():
    """
    Volumetric weight is larger → used as billable weight.
    dims: 50×40×30 → vol = 12.0 kg  |  actual = 2.0 kg → billable = 12.0
    charge = 30 + 12 × 5 = 90
    """
    db = make_db(zones=[NORTH_ZONE, SOUTH_ZONE], rate_card=INTRA_B2C_RATE)
    result = await calculate_charge(
        pickup_address="Karol Bagh 110001",
        drop_address="110001",
        dimensions={"l": 50, "b": 40, "h": 30},
        actual_weight=2.0,
        order_type="B2C",
        payment_type="prepaid",
        db=db,
    )
    assert result.volumetric_weight == pytest.approx(12.0)
    assert result.billable_weight == pytest.approx(12.0)
    assert result.base_charge == pytest.approx(90.0)


@pytest.mark.asyncio
async def test_inter_zone_b2c_cod():
    """
    North → South (inter), B2C, COD.
    actual=3kg, vol=(20×15×10)/5000=0.6kg → billable=3kg
    charge = 60 + 3×8 + 25 (COD) = 109
    """
    db = make_db(
        zones=[NORTH_ZONE, SOUTH_ZONE],
        rate_card=INTER_B2C_RATE,
        cod_surcharge=COD_SURCHARGE_B2C,
    )
    result = await calculate_charge(
        pickup_address="110001 Karol Bagh",
        drop_address="110017 Hauz Khas",
        dimensions={"l": 20, "b": 15, "h": 10},
        actual_weight=3.0,
        order_type="B2C",
        payment_type="COD",
        db=db,
    )
    assert result.zone_relation == "inter"
    assert result.cod_surcharge == 25.0
    assert result.final_charge == pytest.approx(109.0)


@pytest.mark.asyncio
async def test_inter_zone_b2b_cod():
    """
    North → South (inter), B2B, COD.
    actual=10kg, vol=(30×30×20)/5000=3.6kg → billable=10kg
    charge = 100 + 10×12 + 50 (COD B2B) = 270
    """
    db = make_db(
        zones=[NORTH_ZONE, SOUTH_ZONE],
        rate_card=INTER_B2B_RATE,
        cod_surcharge=COD_SURCHARGE_B2B,
    )
    result = await calculate_charge(
        pickup_address="110001 Karol Bagh",
        drop_address="110017 Hauz Khas",
        dimensions={"l": 30, "b": 30, "h": 20},
        actual_weight=10.0,
        order_type="B2B",
        payment_type="COD",
        db=db,
    )
    assert result.base_charge == pytest.approx(220.0)
    assert result.cod_surcharge == 50.0
    assert result.final_charge == pytest.approx(270.0)


@pytest.mark.asyncio
async def test_zone_not_found_raises():
    """Address with no matching area raises ZoneNotFoundError."""
    # Return empty zones on every call
    db = MockDB({"zones": MockCollection(docs=[])})

    with pytest.raises(ZoneNotFoundError):
        await calculate_charge(
            pickup_address="Unknown Place XYZ",
            drop_address="Another Unknown",
            dimensions={"l": 10, "b": 10, "h": 10},
            actual_weight=1.0,
            order_type="B2C",
            payment_type="prepaid",
            db=db,
        )


@pytest.mark.asyncio
async def test_rate_card_not_found_raises():
    """Missing rate card raises RateCardNotFoundError."""
    db = make_db(
        zones=[NORTH_ZONE, SOUTH_ZONE],
        rate_card=None,  # no matching rate card
    )
    with pytest.raises(RateCardNotFoundError):
        await calculate_charge(
            pickup_address="110001 Karol Bagh",
            drop_address="110017 Hauz Khas",
            dimensions={"l": 10, "b": 10, "h": 10},
            actual_weight=1.0,
            order_type="B2C",
            payment_type="prepaid",
            db=db,
        )


@pytest.mark.asyncio
async def test_cod_surcharge_not_added_for_prepaid():
    """Prepaid orders should have 0 COD surcharge even if config exists."""
    db = make_db(
        zones=[NORTH_ZONE, SOUTH_ZONE],
        rate_card=INTER_B2C_RATE,
        cod_surcharge=COD_SURCHARGE_B2C,
    )
    result = await calculate_charge(
        pickup_address="110001 Karol Bagh",
        drop_address="110017 Hauz Khas",
        dimensions={"l": 10, "b": 10, "h": 10},
        actual_weight=3.0,
        order_type="B2C",
        payment_type="prepaid",
        db=db,
    )
    assert result.cod_surcharge == 0.0
    assert result.final_charge == result.base_charge
