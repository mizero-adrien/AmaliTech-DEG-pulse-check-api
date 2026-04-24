import os

from dotenv import load_dotenv
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ApiKey, User
from app.services.jwt_handler import verify_token

load_dotenv()


async def verify_api_key(
    api_key: str = Header(None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
):
    if api_key is None:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key")
    master_key = os.getenv("API_KEY", "pulse-check-secret-key-2026")
    if api_key == master_key:
        return api_key
    result = await db.execute(
        select(ApiKey).where(ApiKey.key == api_key, ApiKey.is_active == True)  # noqa: E712
    )
    db_key = result.scalar_one_or_none()
    if not db_key:
        raise HTTPException(status_code=403, detail="Invalid or missing API Key")
    return api_key


async def verify_jwt(
    authorization: str = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> User:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.removeprefix("Bearer ")
    email = verify_token(token)
    if email is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def verify_any_auth(
    api_key: str = Header(None, alias="X-API-Key"),
    authorization: str = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
):
    if api_key is not None:
        master_key = os.getenv("API_KEY", "pulse-check-secret-key-2026")
        if api_key == master_key:
            return api_key
        result = await db.execute(
            select(ApiKey).where(ApiKey.key == api_key, ApiKey.is_active == True)  # noqa: E712
        )
        if result.scalar_one_or_none():
            return api_key

    if authorization is not None and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
        email = verify_token(token)
        if email is not None:
            result = await db.execute(
                select(User).where(User.email == email, User.is_active == True)  # noqa: E712
            )
            user = result.scalar_one_or_none()
            if user is not None:
                return user

    raise HTTPException(status_code=403, detail="Valid API key or JWT token required")
