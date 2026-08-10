import time
from typing import AsyncIterator

import google.generativeai as genai

from app.providers.base import BaseProvider, ChatMessage, ProviderResponse, StreamChunk

# $ per 1M tokens (input, output)
PRICING = {
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (1.25, 5.00),
}


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        in_price, out_price = PRICING.get(model, PRICING["gemini-2.0-flash"])
        return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price

    def _build(self, messages: list[ChatMessage], model: str):
        system = "\n".join(m.content for m in messages if m.role == "system") or None
        history = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [m.content]}
            for m in messages
            if m.role != "system"
        ]
        gm = genai.GenerativeModel(model_name=model, system_instruction=system)
        return gm, history

    async def chat(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ProviderResponse:
        start = time.perf_counter()
        gm, history = self._build(messages, model)
        convo = history[:-1]
        last = history[-1]["parts"][0]
        chat_session = gm.start_chat(history=convo)
        resp = await chat_session.send_message_async(
            last,
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        latency_ms = (time.perf_counter() - start) * 1000
        in_tok = resp.usage_metadata.prompt_token_count
        out_tok = resp.usage_metadata.candidates_token_count
        cost = self.estimate_cost(in_tok, out_tok, model)
        return ProviderResponse(
            content=resp.text,
            input_tokens=in_tok,
            output_tokens=out_tok,
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
        gm, history = self._build(messages, model)
        convo = history[:-1]
        last = history[-1]["parts"][0]
        chat_session = gm.start_chat(history=convo)
        resp = await chat_session.send_message_async(
            last,
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
            stream=True,
        )
        in_tok = 0
        out_tok = 0
        async for chunk in resp:
            if chunk.text:
                yield StreamChunk(delta=chunk.text)
            if chunk.usage_metadata:
                in_tok = chunk.usage_metadata.prompt_token_count
                out_tok = chunk.usage_metadata.candidates_token_count

        latency_ms = (time.perf_counter() - start) * 1000
        cost = self.estimate_cost(in_tok, out_tok, model)
        yield StreamChunk(
            delta="",
            finished=True,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            latency_ms=latency_ms,
        )
