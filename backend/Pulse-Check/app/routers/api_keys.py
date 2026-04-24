import logging
import secrets
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ApiKey
from app.schemas import ApiKeyCreate, ApiKeyOut
from app.security import verify_jwt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api-keys", tags=["api-keys"])


@router.post("/generate", response_model=ApiKeyOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(verify_jwt)])
async def generate_api_key(payload: ApiKeyCreate, db: AsyncSession = Depends(get_db)):
    key_value = "psk_live_" + secrets.token_hex(24)
    api_key = ApiKey(
        key=key_value,
        device_id=payload.device_id,
        name=payload.name,
        is_active=True,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)
    logger.info(
        "API key generated: device='%s' name='%s' key_prefix='%s...'",
        payload.device_id,
        payload.name,
        key_value[:16],
    )
    return api_key


@router.get("", response_model=List[ApiKeyOut], dependencies=[Depends(verify_jwt)])
async def list_api_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ApiKey).where(ApiKey.is_active == True).order_by(ApiKey.created_at.desc())  # noqa: E712
    )
    return result.scalars().all()


@router.delete("/{key_id}", dependencies=[Depends(verify_jwt)])
async def deactivate_api_key(key_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {key_id} not found",
        )
    api_key.is_active = False
    await db.commit()
    logger.info("API key %d deactivated", key_id)
    return {"message": f"API key {key_id} deactivated successfully"}
