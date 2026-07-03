"""
FastAPI dependency injection — authentication and role-based access control.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.database import get_db
from backend.services.auth_service import decode_token
from backend.models.user import UserInDB

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> UserInDB:
    """Decode JWT and return the current user document from DB."""
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
    if user_doc is None:
        raise credentials_exc

    return UserInDB(**user_doc)


def require_roles(*roles: str):
    """
    Factory that returns a FastAPI dependency enforcing role membership.
    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_roles("admin"))])
    or as a function parameter:
        current_user: UserInDB = Depends(require_roles("admin", "customer"))
    """
    async def _check(
        current_user: UserInDB = Depends(get_current_user),
    ) -> UserInDB:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role(s): {list(roles)}",
            )
        return current_user

    return _check
