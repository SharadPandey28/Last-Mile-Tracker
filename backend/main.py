"""
Last-Mile Delivery Tracker — FastAPI Application Entry Point

Serves:
  - REST API at /api/* (via routers)
  - OpenAPI docs at /docs and /redoc
  - Static frontend files from /frontend/
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from bson import ObjectId
import os

from backend.database import get_client, close_client, get_db
from backend.routes import auth, admin, customer, agent
from backend.dependencies import get_current_user
from backend.services.order_service import get_tracking_history

from fastapi import APIRouter, BackgroundTasks, HTTPException
from datetime import datetime, timezone
from backend.services.email_services import send_delivery_status_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify DB connection. Shutdown: close Motor client."""
    logger.info("Starting Last-Mile Delivery Tracker API...")
    client = get_client()
    try:
        await client.admin.command("ping")
        logger.info("MongoDB connection verified.")
    except Exception as e:
        logger.error("MongoDB connection failed: %s", e)
    yield
    await close_client()
    logger.info("MongoDB client closed.")


app = FastAPI(
    title="Last-Mile Delivery Tracker",
    description="""
## Last-Mile Delivery Management Platform

Role-based delivery tracking platform with:
- **Customer**: Place orders, track deliveries, reschedule failed deliveries
- **Delivery Agent**: View assigned orders, update delivery status
- **Admin**: Manage zones, rate cards, agents, and all orders

### Authentication
All endpoints (except `/auth/register` and `/auth/login`) require a Bearer JWT token.
Obtain a token via `/auth/login`.
    """,
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins in dev; restrict in production via env
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Routers ───────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(customer.router, prefix="/api")
app.include_router(agent.router, prefix="/api")


# ── Shared tracking endpoint ──────────────────────────────────────────────────
@app.get("/api/tracking/{order_id}", tags=["Shared"])
async def shared_tracking(
    order_id: str,
    db=Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Return tracking history for an order.
    - Customers can only see their own orders.
    - Agents can see orders assigned to them.
    - Admins see all.
    """
    try:
        order = await db["orders"].find_one({"_id": ObjectId(order_id)})
    except Exception:
        raise HTTPException(400, "Invalid order ID")
    if not order:
        raise HTTPException(404, "Order not found")

    role = current_user.role
    uid = str(current_user.id)

    if role == "customer" and order.get("customer_id") != uid:
        raise HTTPException(403, "Access denied")
    if role == "delivery_agent" and order.get("assigned_agent_id") != uid:
        raise HTTPException(403, "Access denied")

    return await get_tracking_history(order_id, db)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["Health"])
async def health():
    return {"status": "ok", "service": "last-mile-tracker"}


# ── Static frontend ───────────────────────────────────────────────────────────
# Determine the frontend directory relative to this file
_here = os.path.dirname(os.path.abspath(__file__))
_frontend_dir = os.path.join(os.path.dirname(_here), "frontend")

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/login.html")

# Email_services_approach
email_router = APIRouter()

@email_router.patch("/test_orders/{order_id}/status")
async def update_delivery_status(order_id: str, new_status: str, background_tasks: BackgroundTasks, db=Depends(get_db)):
    try:
        oid = ObjectId(order_id)
    except:
        oid = order_id
        
    order = await db.orders.find_one({"_id": oid})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    await db.orders.update_one(
        {"_id": oid},
        {"$set": {"current_status": new_status, "updated_at": datetime.now(timezone.utc)}}
    )

    customer = await db.users.find_one({"_id": ObjectId(order["customer_id"])})
    if customer:
        background_tasks.add_task(
            send_delivery_status_email,
            to=customer.get("email", ""),
            customer_name=customer.get("name", ""),
            order_id=str(order_id),
            status=new_status,
            tracking_url=f"https://yourapp.com/track/{order_id}"
        )

    return {"message": "Status updated", "order_id": order_id, "status": new_status}    

app.include_router(email_router, prefix="/api")

if os.path.isdir(_frontend_dir):
    app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
else:
    logger.warning("Frontend directory not found at %s — static files not served.", _frontend_dir)
