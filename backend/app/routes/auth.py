from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from app.crypto import generate_gateway_key, hash_gateway_key
from app.database import SessionLocal
from app.models import ApiKey, User
from app.schemas import ApiKeyCreated

router = APIRouter(prefix="/api/auth", tags=["auth"])
@router.post("/signup", response_model=ApiKeyCreated)
async def signup(email: str):
    async with SessionLocal() as db:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=400, detail="Email already registered — use an existing key instead")

        user = User(email=email)
        db.add(user)
        await db.flush() 

        raw_key = generate_gateway_key()
        api_key = ApiKey(user_id=user.id, key_hash=hash_gateway_key(raw_key), name="Default key")
        db.add(api_key)
        await db.commit()
        await db.refresh(api_key)

        return ApiKeyCreated(
            id=str(api_key.id), name=api_key.name, status=api_key.status,
            created_at=api_key.created_at, last_used_at=api_key.last_used_at,
            raw_key=raw_key,
        )
