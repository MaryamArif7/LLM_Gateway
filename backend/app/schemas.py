from datetime import datetime

from pydantic import BaseModel


class ApiKeyCreate(BaseModel):
    name: str = "Default key"


class ApiKeyOut(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    raw_key: str  


class ProviderKeyCreate(BaseModel):
    provider: str  
    api_key: str


class ProviderKeyOut(BaseModel):
    id: str
    provider: str
    key_last4: str
    status: str
    created_at: datetime


class ChatMessageIn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    messages: list[ChatMessageIn]
    model: str | None = None  
    temperature: float = 0.7
    max_tokens: int = 1024


class CompareRequest(BaseModel):
    prompt: str
    models: list[str]  
    temperature: float = 0.7
    max_tokens: int = 1024
