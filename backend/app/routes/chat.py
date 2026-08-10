import json
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select

from app.cache import check_rate_limit, fingerprint, get_cached_response, set_cached_response
from app.database import SessionLocal
from app.models import Conversation, Message, RequestLog
from app.providers import get_provider
from app.providers.base import ChatMessage
from app.router.router import decide_route
from app.schemas import ChatRequest

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data)}


@router.post("/stream")
async def chat_stream(req: ChatRequest, request: Request):
    client_id = request.client.host if request.client else "anonymous"
    allowed, remaining = await check_rate_limit(client_id)
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a bit.")

    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    last_user_prompt = req.messages[-1].content
    decision = decide_route(last_user_prompt, override_model=req.model)
    chain = decision.chain
    plain_messages = [{"role": m.role, "content": m.content} for m in req.messages]

    async def event_generator():
        # --- cache check (only against the top-of-chain model) ---
        top_provider, top_model = chain[0]
        cache_key = fingerprint(top_model, plain_messages, req.temperature)
        cached = await get_cached_response(cache_key)

        conversation_id = req.conversation_id or str(uuid.uuid4())

        if cached:
            yield _sse("meta", {
                "provider": top_provider, "model": top_model,
                "classification": decision.classification.query_type.value,
                "reason": decision.classification.reason,
                "cache_hit": True, "conversation_id": conversation_id,
            })
            # replay cached content as a single chunk — still a real stream
            # from the client's perspective, just instant
            yield _sse("delta", {"text": cached["content"]})
            yield _sse("done", {
                "input_tokens": cached["input_tokens"], "output_tokens": cached["output_tokens"],
                "cost_usd": 0.0,  # cache hits cost nothing — that's the point
                "latency_ms": 5, "cache_hit": True, "fallback_used": False,
            })
            await _persist(conversation_id, req, cached["content"], top_provider, top_model,
                            decision, cached["input_tokens"], cached["output_tokens"],
                            0.0, 5, True, False, None)
            return

        # --- try providers in fallback order ---
        last_error = None
        for i, (provider_name, model_name) in enumerate(chain):
            fallback_used = i > 0
            try:
                provider = get_provider(provider_name)
                yield _sse("meta", {
                    "provider": provider_name, "model": model_name,
                    "classification": decision.classification.query_type.value,
                    "reason": decision.classification.reason,
                    "cache_hit": False, "fallback_used": fallback_used,
                    "conversation_id": conversation_id,
                })

                full_text = ""
                start = time.perf_counter()
                async for chunk in provider.chat_stream(
                    [ChatMessage(role=m["role"], content=m["content"]) for m in plain_messages],
                    model_name, req.temperature, req.max_tokens,
                ):
                    if not chunk.finished:
                        full_text += chunk.delta
                        yield _sse("delta", {"text": chunk.delta})
                    else:
                        yield _sse("done", {
                            "input_tokens": chunk.input_tokens, "output_tokens": chunk.output_tokens,
                            "cost_usd": chunk.cost_usd, "latency_ms": chunk.latency_ms,
                            "cache_hit": False, "fallback_used": fallback_used,
                        })
                        await set_cached_response(cache_key, {
                            "content": full_text,
                            "input_tokens": chunk.input_tokens,
                            "output_tokens": chunk.output_tokens,
                        })
                        await _persist(conversation_id, req, full_text, provider_name, model_name,
                                        decision, chunk.input_tokens, chunk.output_tokens,
                                        chunk.cost_usd, chunk.latency_ms, False, fallback_used, None)
                return  # success — stop trying further providers
            except Exception as e:  # noqa: BLE001 — deliberately broad: any provider failure triggers fallback
                last_error = str(e)
                yield _sse("provider_error", {"provider": provider_name, "model": model_name, "error": last_error})
                continue

        # every provider in the chain failed
        yield _sse("error", {"message": f"All providers failed. Last error: {last_error}"})
        await _persist(conversation_id, req, "", chain[-1][0], chain[-1][1], decision,
                        0, 0, 0.0, 0, False, True, last_error)

    return EventSourceResponse(event_generator())


async def _persist(conversation_id, req, content, provider, model, decision,
                    input_tokens, output_tokens, cost_usd, latency_ms,
                    cache_hit, fallback_used, error):
    async with SessionLocal() as session:
        result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        convo = result.scalar_one_or_none()
        if convo is None:
            convo = Conversation(id=conversation_id, title=req.messages[-1].content[:60])
            session.add(convo)

        session.add(Message(conversation_id=conversation_id, role="user", content=req.messages[-1].content))
        if content:
            session.add(Message(conversation_id=conversation_id, role="assistant", content=content))

        session.add(RequestLog(
            conversation_id=conversation_id, provider=provider, model=model,
            classification=decision.classification.query_type.value,
            route_reason=decision.classification.reason,
            input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=cost_usd, latency_ms=latency_ms,
            cache_hit=cache_hit, fallback_used=fallback_used, error=error,
        ))
        await session.commit()
