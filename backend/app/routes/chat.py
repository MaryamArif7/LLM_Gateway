import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse
from sqlalchemy import select

from app import metrics, provider_health
from app.auth import get_current_user
from app.cache import check_rate_limit, fingerprint, get_cached_response, set_cached_response
from app.crypto import decrypt_provider_key
from app.database import SessionLocal
from app.models import Conversation, Message, ProviderKey, RequestLog, User
from app.providers import get_provider
from app.providers.base import ChatMessage
from app.request_plan import resolve_plan
from app.usage_events import new_usage_row, record_usage
from app.router.router import decide_route
from app.schemas import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


async def _load_provider_keys(user_id) -> dict[str, str]:

    async with SessionLocal() as db:
        result = await db.execute(select(ProviderKey).where(ProviderKey.user_id == user_id))
        return {row.provider: decrypt_provider_key(row.encrypted_key) for row in result.scalars().all()}


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data)}


@router.post("/stream")
async def chat_stream(req: ChatRequest, request: Request, user: User = Depends(get_current_user)):

    allowed, remaining = await check_rate_limit(str(user.id))
    if not allowed:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a bit.")

    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    provider_keys = await _load_provider_keys(user.id)
    if not provider_keys:
        raise HTTPException(
            status_code=400,
            detail="No provider keys connected. Add at least one in /dashboard/providers first.",
        )

    plan = await resolve_plan(user.id, req)

    last_user_prompt = req.messages[-1].content
    try:
        decision = decide_route(last_user_prompt, override_model=plan.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    chain = [(p, m) for p, m in decision.chain if p in provider_keys]
    if not chain:
        raise HTTPException(
            status_code=400,
            detail=f"None of your connected providers ({', '.join(provider_keys)}) match the routed model. "
                   f"Connect {decision.chain[0][0]} or pin a different model.",
        )
    plain_messages = [{"role": m.role, "content": m.content} for m in req.messages]
    if plan.system_text:
        plain_messages = [{"role": "system", "content": plan.system_text}] + plain_messages

    plan_meta = plan.meta()
    log_extra = dict(
        user_id=user.id, feature_tag=req.feature_tag,
        experiment_id=plan.experiment_id, variant=plan.variant,
        prompt_name=plan.prompt_name, prompt_version=plan.prompt_version,
    )

    route_class = decision.classification.query_type.value
    served = {"provider": chain[0][0], "model": chain[0][1], "strategy": "direct", "skipped": []}

    async def event_generator():
     
        top_provider, top_model = chain[0]
        cache_key = fingerprint(str(user.id), top_model, plain_messages, req.temperature)
        cached = await get_cached_response(cache_key)

        conversation_id = req.conversation_id or str(uuid.uuid4())

        if cached:
            metrics.CACHE_LOOKUPS.labels("hit").inc()
            metrics.REQUESTS.labels("chat", top_provider, top_model, "success", "false").inc()
            served["strategy"] = "cache"
            yield _sse("meta", {
                "provider": top_provider, "model": top_model,
                "classification": route_class,
                "reason": decision.classification.reason,
                "cache_hit": True, "conversation_id": conversation_id, **plan_meta,
            })
           
            yield _sse("delta", {"text": cached["content"]})
            await _persist_safe(conversation_id, req, cached["content"], top_provider, top_model,
                                decision, cached["input_tokens"], cached["output_tokens"],
                                0.0, 5, True, False, None,
                                **log_extra)
            yield _sse("done", {
                "input_tokens": cached["input_tokens"], "output_tokens": cached["output_tokens"],
                "cost_usd": 0.0,
                "latency_ms": 5, "cache_hit": True, "fallback_used": False,
            })
            return
        metrics.CACHE_LOOKUPS.labels("miss").inc()
        states = await provider_health.provider_states(list(dict.fromkeys(p for p, _ in chain)))
        ignore_breakers = all(state == "open" for state in states.values())

        last_error = None
        attempted = 0
        for i, (provider_name, model_name) in enumerate(chain):
            fallback_used = i > 0
            state = states.get(provider_name, "closed")
            if not ignore_breakers and (
                state == "open" or (state == "half_open" and not await provider_health.claim_probe(provider_name))
            ):
                metrics.ATTEMPTS.labels(provider_name, model_name, "skipped_open").inc()
                if provider_name not in served["skipped"]:
                    served["skipped"].append(provider_name)
                continue

            attempted += 1
            served.update(provider=provider_name, model=model_name, strategy="fallback" if fallback_used else "direct")
            try:
                provider = get_provider(provider_name, provider_keys[provider_name])
                yield _sse("meta", {
                    "provider": provider_name, "model": model_name,
                    "classification": route_class,
                    "reason": decision.classification.reason,
                    "cache_hit": False, "fallback_used": fallback_used,
                    "conversation_id": conversation_id, **plan_meta,
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
                        metrics.ATTEMPTS.labels(provider_name, model_name, "success").inc()
                        metrics.PROVIDER_DURATION.labels(provider_name, model_name).observe(time.perf_counter() - start)
                        metrics.REQUESTS.labels("chat", provider_name, model_name, "success", str(fallback_used).lower()).inc()
                        await provider_health.record(provider_name, "ok")
                        try:
                            await set_cached_response(cache_key, {
                                "content": full_text,
                                "input_tokens": chunk.input_tokens,
                                "output_tokens": chunk.output_tokens,
                            })
                        except Exception:
                            logger.warning("could not write response cache", exc_info=True)
                        await _persist_safe(conversation_id, req, full_text, provider_name, model_name,
                                            decision, chunk.input_tokens, chunk.output_tokens,
                                            chunk.cost_usd, chunk.latency_ms, False, fallback_used, None,
                                            **log_extra)
                        yield _sse("done", {
                            "input_tokens": chunk.input_tokens, "output_tokens": chunk.output_tokens,
                            "cost_usd": chunk.cost_usd, "latency_ms": chunk.latency_ms,
                            "cache_hit": False, "fallback_used": fallback_used,
                        })
                return
            except Exception as e:  
                last_error = str(e)
                kind = provider_health.classify_failure(e)
                metrics.ATTEMPTS.labels(provider_name, model_name, "upstream_error" if kind == "upstream" else "client_error").inc()
                await provider_health.record(provider_name, kind)
                yield _sse("provider_error", {"provider": provider_name, "model": model_name, "error": last_error})
                continue

        if attempted == 0:
            last_error = "every provider is cooling down after repeated failures, try again shortly"
        served.update(provider="none", model="none", strategy="failed")
        metrics.REQUESTS.labels("chat", "none", "none", "error", str(attempted > 1).lower()).inc()
        yield _sse("error", {"message": f"All providers failed. Last error: {last_error}"})
        await _persist_safe(conversation_id, req, "", chain[-1][0], chain[-1][1], decision,
                            0, 0, 0.0, 0, False, True, last_error,
                            **log_extra)
    gen = event_generator()
    held = []
    try:
        async for event in gen:
            held.append(event)
            if event["event"] in ("delta", "done", "error"):
                break
    except BaseException:
        await gen.aclose()
        raise

    async def replay():
        try:
            for event in held:
                yield event
            async for event in gen:
                yield event
        finally:
            await gen.aclose()

    return EventSourceResponse(replay(), headers={"X-Gateway-Decision": decision_header(served, route_class)})


def decision_header(served: dict, route_class: str) -> str:
    parts = [
        f"provider={served['provider']}", f"model={served['model']}",
        f"strategy={served['strategy']}", f"route={route_class}",
    ]
    if served["skipped"]:
        parts.append("skipped=" + "+".join(served["skipped"]))
    return ", ".join(parts)


async def _persist(conversation_id, req, content, provider, model, decision,
                    input_tokens, output_tokens, cost_usd, latency_ms,
                    cache_hit, fallback_used, error, user_id=None, feature_tag=None,
                    experiment_id=None, variant=None, prompt_name=None, prompt_version=None):
    conversation_saved = True
    try:
        async with SessionLocal() as session:
            result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
            convo = result.scalar_one_or_none()
            if convo is None:
                convo = Conversation(id=conversation_id, title=req.messages[-1].content[:60])
                session.add(convo)

            session.add(Message(conversation_id=conversation_id, role="user", content=req.messages[-1].content))
            if content:
                session.add(Message(conversation_id=conversation_id, role="assistant", content=content))
            await session.commit()
    except Exception:
        conversation_saved = False
        logger.warning("could not save conversation history", exc_info=True)
    await record_usage(new_usage_row(
        conversation_id=uuid.UUID(str(conversation_id)) if conversation_saved else None,
        provider=provider, model=model,
        classification=decision.classification.query_type.value,
        route_reason=decision.classification.reason,
        input_tokens=input_tokens, output_tokens=output_tokens,
        cost_usd=cost_usd, latency_ms=latency_ms,
        cache_hit=cache_hit, fallback_used=fallback_used, error=error,
        user_id=user_id, feature_tag=feature_tag,
        experiment_id=experiment_id, variant=variant,
        prompt_name=prompt_name, prompt_version=prompt_version,
    ))


async def _persist_safe(*args, **kwargs):
    try:
        await _persist(*args, **kwargs)
    except Exception:
        logger.exception("could not write request log")
