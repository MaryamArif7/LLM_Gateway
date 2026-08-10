import time
from typing import AsyncIterator

from openai import AsyncOpenAI

from app.providers.base import BaseProvider, ChatMessage, ProviderResponse, StreamChunk

# $ per 1M tokens (input, output) — update as pricing changes
PRICING = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
}


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        in_price, out_price = PRICING.get(model, PRICING["gpt-4o-mini"])
        return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        start = time.perf_counter()
        resp = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        usage = resp.usage
        cost = self.estimate_cost(usage.prompt_tokens, usage.completion_tokens, model)
        return ProviderResponse(
            content=resp.choices[0].message.content,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            model=model,
            provider=self.name,
            latency_ms=latency_ms,
            cost_usd=cost,
        )

    async def chat_stream(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunk]:
        start = time.perf_counter()
        output_text = ""
        stream = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        input_tokens = 0
        output_tokens = 0
        async for chunk in stream:
            if chunk.usage:
                input_tokens = chunk.usage.prompt_tokens
                output_tokens = chunk.usage.completion_tokens
            if chunk.choices and chunk.choices[0].delta.content:
                delta = chunk.choices[0].delta.content
                output_text += delta
                yield StreamChunk(delta=delta)

        latency_ms = (time.perf_counter() - start) * 1000
        cost = self.estimate_cost(input_tokens, output_tokens, model)
        yield StreamChunk(
            delta="",
            finished=True,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
        )
