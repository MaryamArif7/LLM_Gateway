import time
from typing import AsyncIterator

from anthropic import AsyncAnthropic

from app.providers.base import BaseProvider, ChatMessage, ProviderResponse, StreamChunk

# $ per 1M tokens (input, output)
PRICING = {
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-opus-4-1-20250805": (15.00, 75.00),
}


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, api_key: str):
        self.client = AsyncAnthropic(api_key=api_key)

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        in_price, out_price = PRICING.get(model, PRICING["claude-haiku-4-5-20251001"])
        return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price

    def _split_system(self, messages: list[ChatMessage]):
        system = "\n".join(m.content for m in messages if m.role == "system") or None
        rest = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        return system, rest

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        start = time.perf_counter()
        system, rest = self._split_system(messages)
        resp = await self.client.messages.create(
            model=model,
            system=system,
            messages=rest,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        cost = self.estimate_cost(resp.usage.input_tokens, resp.usage.output_tokens, model)
        return ProviderResponse(
            content=resp.content[0].text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
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
        system, rest = self._split_system(messages)
        input_tokens = 0
        output_tokens = 0

        async with self.client.messages.stream(
            model=model,
            system=system,
            messages=rest,
            temperature=temperature,
            max_tokens=max_tokens,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield StreamChunk(delta=event.delta.text)
                elif event.type == "message_start":
                    input_tokens = event.message.usage.input_tokens
                elif event.type == "message_delta":
                    output_tokens = event.usage.output_tokens

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
