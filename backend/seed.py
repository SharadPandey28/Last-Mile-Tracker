"""
Seed script — populates the database with initial data on first run.

Idempotent: checks existence before inserting.
Run with: python backend/seed.py  (from the project root)

Seeds:
  - 1 admin account
  - 3 zones (North, South, East) with pincodes
  - Rate cards (B2B/B2C × intra/inter for each zone pair)
  - COD surcharge config (B2B and B2C)
"""
import asyncio
import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from backend.config import get_settings
from backend.services.auth_service import hash_password
from datetime import datetime, timezone


async def seed():
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]

    print("=== Last-Mile Tracker Seed Script ===")

    # ── Admin account ──────────────────────────────────────────────────────────
    existing_admin = await db["users"].find_one({"role": "admin"})
    if existing_admin:
        print("✓ Admin account already exists — skipping.")
    else:
        result = await db["users"].insert_one({
            "name": "Super Admin",
            "email": "admin@lastmile.com",
            "password_hash": hash_password("Admin@1234"),
            "role": "admin",
            "zone": None,
            "agent_status": None,
            "created_at": datetime.now(timezone.utc),
        })
        print(f"✓ Admin created — email: admin@lastmile.com | password: Admin@1234")

    # ── Zones ──────────────────────────────────────────────────────────────────
    zone_data = [
        {
            "name": "North Zone",
            "areas": ["110001", "110002", "110003", "Connaught Place", "Karol Bagh", "Rohini"]
        },
        {
            "name": "South Zone",
            "areas": ["110017", "110022", "110044", "Hauz Khas", "Saket", "Mehrauli"]
        },
        {
            "name": "East Zone",
            "areas": ["110032", "110091", "110092", "Laxmi Nagar", "Preet Vihar", "Shahdara"]
        },
    ]

    zone_ids = {}
    for z in zone_data:
        existing = await db["zones"].find_one({"name": z["name"]})
        if existing:
            zone_ids[z["name"]] = str(existing["_id"])
            print(f"✓ Zone '{z['name']}' already exists — skipping.")
        else:
            result = await db["zones"].insert_one(z)
            zone_ids[z["name"]] = str(result.inserted_id)
            print(f"✓ Zone '{z['name']}' created with {len(z['areas'])} areas.")

    north_id = zone_ids["North Zone"]
    south_id = zone_ids["South Zone"]
    east_id  = zone_ids["East Zone"]

    # ── Rate Cards ─────────────────────────────────────────────────────────────
    # Intra-zone cards (same pickup and drop zone)
    # Inter-zone cards for each combination
    rate_cards = [
        # Intra-zone
        {"order_type": "B2C", "zone_relation": "intra", "from_zone_id": north_id, "to_zone_id": north_id, "base_rate": 30.0, "per_kg_rate": 5.0},
        {"order_type": "B2C", "zone_relation": "intra", "from_zone_id": south_id, "to_zone_id": south_id, "base_rate": 30.0, "per_kg_rate": 5.0},
        {"order_type": "B2C", "zone_relation": "intra", "from_zone_id": east_id,  "to_zone_id": east_id,  "base_rate": 30.0, "per_kg_rate": 5.0},
        {"order_type": "B2B", "zone_relation": "intra", "from_zone_id": north_id, "to_zone_id": north_id, "base_rate": 50.0, "per_kg_rate": 8.0},
        {"order_type": "B2B", "zone_relation": "intra", "from_zone_id": south_id, "to_zone_id": south_id, "base_rate": 50.0, "per_kg_rate": 8.0},
        {"order_type": "B2B", "zone_relation": "intra", "from_zone_id": east_id,  "to_zone_id": east_id,  "base_rate": 50.0, "per_kg_rate": 8.0},
        # Inter-zone B2C
        {"order_type": "B2C", "zone_relation": "inter", "from_zone_id": north_id, "to_zone_id": south_id, "base_rate": 60.0, "per_kg_rate": 8.0},
        {"order_type": "B2C", "zone_relation": "inter", "from_zone_id": north_id, "to_zone_id": east_id,  "base_rate": 60.0, "per_kg_rate": 8.0},
        {"order_type": "B2C", "zone_relation": "inter", "from_zone_id": south_id, "to_zone_id": east_id,  "base_rate": 60.0, "per_kg_rate": 8.0},
        # Inter-zone B2B
        {"order_type": "B2B", "zone_relation": "inter", "from_zone_id": north_id, "to_zone_id": south_id, "base_rate": 100.0, "per_kg_rate": 12.0},
        {"order_type": "B2B", "zone_relation": "inter", "from_zone_id": north_id, "to_zone_id": east_id,  "base_rate": 100.0, "per_kg_rate": 12.0},
        {"order_type": "B2B", "zone_relation": "inter", "from_zone_id": south_id, "to_zone_id": east_id,  "base_rate": 100.0, "per_kg_rate": 12.0},
    ]

    for rc in rate_cards:
        existing = await db["rate_cards"].find_one({
            "order_type": rc["order_type"],
            "zone_relation": rc["zone_relation"],
            "from_zone_id": rc["from_zone_id"],
            "to_zone_id": rc["to_zone_id"],
        })
        if existing:
            continue
        rc["updated_by"] = None
        rc["updated_at"] = datetime.now(timezone.utc)
        await db["rate_cards"].insert_one(rc)

    print(f"✓ {len(rate_cards)} rate card entries seeded.")

    # ── COD Surcharge ──────────────────────────────────────────────────────────
    for ot, amount in [("B2C", 25.0), ("B2B", 50.0)]:
        await db["cod_surcharge_config"].update_one(
            {"order_type": ot},
            {"$setOnInsert": {
                "order_type": ot,
                "surcharge_amount": amount,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    print("✓ COD surcharge config seeded (B2C: ₹25, B2B: ₹50).")

    client.close()
    print("\n=== Seed complete! ===")
    print("Admin login: admin@lastmile.com / Admin@1234")
    print("Open http://localhost:8000 to get started.")


if __name__ == "__main__":
    asyncio.run(seed())
