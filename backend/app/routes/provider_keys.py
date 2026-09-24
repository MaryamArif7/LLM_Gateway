from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.crypto import encrypt_provider_key, mask_key
from app.database import get_db
from app.models import ProviderKey, User
from app.schemas import ProviderKeyCreate, ProviderKeyOut

router = APIRouter(prefix="/api/provider-keys", tags=["provider-keys"])

VALID_PROVIDERS = {"openai", "anthropic", "gemini", "mistral"}


@router.post("", response_model=ProviderKeyOut)
async def add_provider_key(
    body: ProviderKeyCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"provider must be one of {sorted(VALID_PROVIDERS)}")


    existing = await db.execute(
        select(ProviderKey).where(ProviderKey.user_id == user.id, ProviderKey.provider == body.provider)
    )
    row = existing.scalar_one_or_none()

    if row is None:
        row = ProviderKey(user_id=user.id, provider=body.provider)
        db.add(row)

    row.encrypted_key = encrypt_provider_key(body.api_key)
    row.key_last4 = mask_key(body.api_key)
    row.status = "unverified" 

    await db.commit()
    await db.refresh(row)
    return ProviderKeyOut(
        id=str(row.id), provider=row.provider, key_last4=row.key_last4,
        status=row.status, created_at=row.created_at,
    )


@router.get("", response_model=list[ProviderKeyOut])
async def list_provider_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProviderKey).where(ProviderKey.user_id == user.id))
    return [
        ProviderKeyOut(id=str(k.id), provider=k.provider, key_last4=k.key_last4, status=k.status, created_at=k.created_at)
        for k in result.scalars().all()
    ]


@router.delete("/{provider_key_id}")
async def remove_provider_key(
    provider_key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ProviderKey).where(ProviderKey.id == provider_key_id, ProviderKey.user_id == user.id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Provider key not found")

    await db.delete(row)
    await db.commit()
    return {"status": "removed"}
