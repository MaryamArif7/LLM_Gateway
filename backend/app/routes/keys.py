from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.crypto import generate_gateway_key, hash_gateway_key
from app.database import get_db
from app.models import ApiKey, User
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut

router = APIRouter(prefix="/api/keys", tags=["keys"])


@router.post("", response_model=ApiKeyCreated)
async def create_key(
    body: ApiKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raw_key = generate_gateway_key()
    api_key = ApiKey(user_id=user.id, key_hash=hash_gateway_key(raw_key), name=body.name)
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    # raw_key is only ever available right here, right now — the database
    # only ever stores the hash, so there is no way to recover it later
    return ApiKeyCreated(
        id=str(api_key.id), name=api_key.name, status=api_key.status,
        created_at=api_key.created_at, last_used_at=api_key.last_used_at,
        raw_key=raw_key,
    )


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    return [
        ApiKeyOut(id=str(k.id), name=k.name, status=k.status, created_at=k.created_at, last_used_at=k.last_used_at)
        for k in result.scalars().all()
    ]


@router.delete("/{key_id}")
async def revoke_key(key_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id))
    api_key = result.scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status_code=404, detail="Key not found")

    api_key.status = "revoked"
    await db.commit()
    return {"status": "revoked"}
