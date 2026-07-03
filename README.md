# Last-Mile Delivery Tracker

A full-stack last-mile delivery management platform with role-based access for **Customer**, **Delivery Agent**, and **Admin** roles. Built with FastAPI + Motor (async MongoDB) + plain HTML/JS frontend.

---

## Table of Contents
1. [Quick Start (Local)](#quick-start-local)
2. [Environment Variables](#environment-variables)
3. [Seed Data](#seed-data)
4. [API Documentation](#api-documentation)
5. [Database Schema](#database-schema)
6. [Rate Calculation Logic](#rate-calculation-logic)
7. [Deployment on Render](#deployment-on-render)

---

## Quick Start (Local)

### Prerequisites
- Python 3.11+
- MongoDB (local or MongoDB Atlas free cluster)

### Steps

```bash
# 1. Clone / navigate to the project
cd last_mile_tracker

# 2. Create and activate a virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create .env file
cp .env.example .env
# Edit .env — set MONGO_URI, JWT_SECRET, email credentials

# 5. Seed the database (creates admin, zones, rate cards, COD config)
python backend/seed.py

# 6. Run the server
uvicorn backend.main:app --reload

# 7. Open the app
#    Frontend: http://localhost:8000
#    API docs: http://localhost:8000/docs
```

### Run Unit Tests

```bash
# From project root
pytest tests/ -v
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

| Variable | Description | Required |
|---|---|---|
| `MONGO_URI` | MongoDB connection string | ✅ |
| `MONGO_DB_NAME` | Database name (default: `last_mile_tracker`) | ✅ |
| `JWT_SECRET` | Secret for signing JWTs — use a long random string | ✅ |
| `JWT_ALGORITHM` | JWT algorithm (default: `HS256`) | — |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime in minutes (default: 60) | — |
| `EMAIL_SENDER` | Gmail address for email notifications | Optional |
| `EMAIL_APP_PASSWORD` | Gmail App Password (not your regular password) | Optional |

**Email setup (Gmail):** Go to your Google Account → Security → 2-Step Verification → App passwords. Create an app password and use it as `EMAIL_APP_PASSWORD`. If no email credentials are set, the app still works — notifications are logged and skipped silently.

---

## Seed Data

The seed script populates the database with starter data:

```bash
python backend/seed.py
```

**What it creates:**
- **Admin account:** `admin@lastmile.com` / `Admin@1234`
- **3 zones:**
  - North Zone: pincodes 110001–110003, Connaught Place, Karol Bagh, Rohini
  - South Zone: pincodes 110017, 110022, 110044, Hauz Khas, Saket, Mehrauli
  - East Zone: pincodes 110032, 110091, 110092, Laxmi Nagar, Preet Vihar, Shahdara
- **Rate cards** — full matrix (B2B/B2C × intra/inter) for all zone pairs
- **COD surcharges:** ₹25 (B2C), ₹50 (B2B)

The script is idempotent — safe to re-run.

---

## API Documentation

### Interactive Docs
The FastAPI auto-generated OpenAPI docs are available at:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

### Authentication
All endpoints except `/api/auth/register` and `/api/auth/login` require:
```
Authorization: Bearer <jwt_token>
```

### Endpoint Summary

#### Auth (`/api/auth`)
| Method | Path | Description | Role |
|---|---|---|---|
| POST | `/auth/register` | Register new customer | Public |
| POST | `/auth/login` | Login (any role) | Public |

#### Admin (`/api/admin`) — requires `admin` role
| Method | Path | Description |
|---|---|---|
| GET/POST | `/admin/zones` | List / Create zones |
| GET/PUT/DELETE | `/admin/zones/{id}` | Get / Update / Delete zone |
| GET/POST | `/admin/rate-cards` | List / Create rate cards |
| PUT/DELETE | `/admin/rate-cards/{id}` | Update / Delete rate card |
| GET/POST | `/admin/cod-surcharge` | List / Upsert COD surcharge |
| DELETE | `/admin/cod-surcharge/{order_type}` | Delete COD config |
| GET/POST | `/admin/agents` | List / Create agent accounts |
| GET | `/admin/orders` | All orders (filters: `?status=&zone=&agent=`) |
| PATCH | `/admin/orders/{id}/status` | Override order status |
| POST | `/admin/orders/{id}/assign` | Manually assign agent |

#### Customer (`/api/customer`) — requires `customer` role
| Method | Path | Description |
|---|---|---|
| POST | `/customer/orders/calculate` | Get charge breakdown (no DB write) |
| POST | `/customer/orders` | Place/confirm order |
| GET | `/customer/orders` | List own orders |
| GET | `/customer/orders/{id}` | Get single order |
| GET | `/customer/orders/{id}/tracking` | Order tracking timeline |
| POST | `/customer/orders/{id}/reschedule` | Submit reschedule date |

#### Agent (`/api/agent`) — requires `delivery_agent` role
| Method | Path | Description |
|---|---|---|
| GET | `/agent/orders` | View assigned orders |
| PATCH | `/agent/orders/{id}/status` | Update order status |
| GET | `/agent/orders/{id}/tracking` | Order tracking timeline |

#### Shared
| Method | Path | Description |
|---|---|---|
| GET | `/api/tracking/{order_id}` | Tracking history (role-filtered) |
| GET | `/api/health` | Health check |

---

## Database Schema

### `users`
```json
{
  "_id": "ObjectId",
  "name": "string",
  "email": "string",
  "password_hash": "string (bcrypt)",
  "role": "customer | delivery_agent | admin",
  "zone": "zone_id (delivery_agent only)",
  "agent_status": "available | busy (delivery_agent only)",
  "created_at": "datetime"
}
```

### `zones`
```json
{
  "_id": "ObjectId",
  "name": "string",
  "areas": ["110001", "Karol Bagh", ...]
}
```
Areas are pincodes or locality names. Zone detection matches these strings against order addresses (case-insensitive substring match).

### `rate_cards`
```json
{
  "_id": "ObjectId",
  "order_type": "B2B | B2C",
  "zone_relation": "intra | inter",
  "from_zone_id": "zone_id",
  "to_zone_id": "zone_id",
  "base_rate": 60.0,
  "per_kg_rate": 8.0,
  "updated_by": "admin_user_id",
  "updated_at": "datetime"
}
```
For intra-zone entries, `from_zone_id == to_zone_id`.

### `cod_surcharge_config`
```json
{
  "_id": "ObjectId",
  "order_type": "B2B | B2C",
  "surcharge_amount": 25.0,
  "updated_at": "datetime"
}
```

### `orders`
```json
{
  "_id": "ObjectId",
  "customer_id": "user_id",
  "created_by": "user_id",
  "pickup_address": "string",
  "drop_address": "string",
  "pickup_zone_id": "zone_id",
  "drop_zone_id": "zone_id",
  "dimensions": { "l": 30, "b": 20, "h": 15 },
  "actual_weight": 2.5,
  "volumetric_weight": 1.8,
  "billable_weight": 2.5,
  "order_type": "B2B | B2C",
  "payment_type": "COD | prepaid",
  "calculated_charge": 109.0,
  "current_status": "Created | Assigned | ...",
  "assigned_agent_id": "user_id",
  "reschedule_date": "datetime | null",
  "created_at": "datetime"
}
```

### `tracking_history` ⚠️ APPEND-ONLY
```json
{
  "_id": "ObjectId",
  "order_id": "string",
  "status": "string",
  "actor_id": "user_id",
  "actor_role": "customer | delivery_agent | admin | system",
  "timestamp": "datetime",
  "notes": "string | null"
}
```
**This collection is strictly append-only. No document is ever updated or deleted. Every status change creates one new document.**

---

## Rate Calculation Logic

The rate engine (`backend/services/rate_engine.py`) follows this sequence:

### Steps

1. **Zone detection** — For each address, iterate all documents in the `zones` collection. For each zone, check if any area string (e.g., `"110001"`, `"Karol Bagh"`) appears as a substring in the address (case-insensitive). First match wins.

2. **Volumetric weight** — `(L × B × H) / 5000` (industry-standard formula, dimensions in cm, result in kg)

3. **Billable weight** — `max(actual_weight, volumetric_weight)`

4. **Zone relation** — `"intra"` if `pickup_zone == drop_zone`, else `"inter"`

5. **Rate card lookup** — Query `rate_cards` for `{order_type, zone_relation, from_zone, to_zone}`. For inter-zone, also try reverse direction (symmetric).

6. **Base charge** — `base_rate + (billable_weight × per_kg_rate)`

7. **COD surcharge** — If `payment_type == "COD"`, look up `cod_surcharge_config` for the order type and add `surcharge_amount`

8. **Final charge** — `base_charge + cod_surcharge`

### Worked Example

**Scenario:** B2C order, North Zone → South Zone (inter), COD, 3 kg actual, 20×15×10 cm box

| Step | Calculation | Result |
|---|---|---|
| Volumetric weight | (20 × 15 × 10) / 5000 | 0.6 kg |
| Billable weight | max(3.0, 0.6) | 3.0 kg |
| Zone relation | North ≠ South | inter |
| Rate card | B2C, inter, North→South | base=₹60, per_kg=₹8 |
| Base charge | 60 + (3.0 × 8) | ₹84.00 |
| COD surcharge | B2C COD config | ₹25.00 |
| **Final charge** | 84 + 25 | **₹109.00** |

---

## Deployment on Render

### Option A — Using `render.yaml` (Recommended)

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → New → Blueprint
3. Connect your GitHub repo — Render detects `render.yaml` automatically
4. In the Render dashboard, set the secret environment variables:
   - `MONGO_URI` — your MongoDB Atlas connection string
   - `JWT_SECRET` — a randomly generated 32+ character string
   - `EMAIL_SENDER` and `EMAIL_APP_PASSWORD` (optional)
5. Click **Deploy**
6. After deploy, run the seed script once:
   ```
   # In Render dashboard → your service → Shell:
   python backend/seed.py
   ```

### Option B — Manual Setup

1. Create a new **Web Service** on Render
2. Set:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Environment:** Python 3.11+
3. Add all environment variables from `.env.example`
4. Deploy and run the seed script via the Render shell

### MongoDB Atlas (Free Tier)

1. Create a free cluster at [cloud.mongodb.com](https://cloud.mongodb.com)
2. Create a database user with read/write access
3. Whitelist `0.0.0.0/0` (or Render's IP ranges) in Network Access
4. Copy the connection string and set it as `MONGO_URI`
