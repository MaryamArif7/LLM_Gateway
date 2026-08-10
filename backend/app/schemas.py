from pydantic import BaseModel


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
