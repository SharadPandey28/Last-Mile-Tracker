"""
Auth routes — customer registration and login.
Admin creates agent accounts via /admin/agents (not here).
"""
from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.database import get_db
from backend.models.user import RegisterRequest, LoginRequest, TokenResponse
from backend.services.auth_service import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Register a new customer account."""
    # Check for duplicate email
    existing = await db["users"].find_one({"email": body.email})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists.",
        )

    user_doc = {
        "name": body.name,
        "email": body.email,
        "password_hash": hash_password(body.password),
        "role": "customer",
        "zone": None,
        "agent_status": None,
        "created_at": __import__("datetime").datetime.utcnow(),
    }
    result = await db["users"].insert_one(user_doc)
    user_id = str(result.inserted_id)

    token = create_access_token({"sub": user_id, "role": "customer", "name": body.name})
    return TokenResponse(access_token=token, role="customer", user_id=user_id, name=body.name)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Login for any role. Returns JWT with role embedded."""
    user = await db["users"].find_one({"email": body.email})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    user_id = str(user["_id"])
    role = user.get("role", "customer")
    name = user.get("name", "")
    token = create_access_token({"sub": user_id, "role": role, "name": name})
    return TokenResponse(access_token=token, role=role, user_id=user_id, name=name)
