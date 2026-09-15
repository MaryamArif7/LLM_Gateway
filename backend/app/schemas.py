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
    raw_key: str  # only ever present in the response to the create call


class ProviderKeyCreate(BaseModel):
    provider: str  # openai | anthropic | gemini | mistral
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
    model: str | None = None  # if set, pins the model (still routed through fallback)
    temperature: float = 0.7
    max_tokens: int = 1024


class CompareRequest(BaseModel):
    prompt: str
    models: list[str]  # e.g. ["gpt-4o", "claude-sonnet-4-5-20250929", "gemini-1.5-pro"]
    temperature: float = 0.7
    max_tokens: int = 1024
