"""
Base provider interface. Every LLM provider (OpenAI, Anthropic, Gemini, ...)
implements this contract so the rest of the gateway never needs to know
which provider it's talking to.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class ProviderResponse:
    content: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
    latency_ms: float
    cost_usd: float


@dataclass
class StreamChunk:
    delta: str
    finished: bool = False
    # populated only on the final chunk
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    latency_ms: Optional[float] = None


class BaseProvider(ABC):
    """All provider adapters normalize to this shape."""

    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        """Non-streaming chat completion."""
        raise NotImplementedError

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming chat completion, yields token deltas."""
        raise NotImplementedError

    @abstractmethod
    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        """Return cost in USD for the given token counts on this model."""
        raise NotImplementedError
