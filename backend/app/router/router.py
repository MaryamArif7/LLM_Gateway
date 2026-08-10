"""
The router's ONLY job is: given a classified query, decide which model to
try first, and in what order to fall back if that call fails. It does not
know about auth, rate limits, or caching — those are separate middleware
layers that wrap around it (see routes/chat.py).
"""
from dataclasses import dataclass

from app.providers import MODEL_PROVIDER_MAP
from app.router.classifier import Classification, QueryType, classify

# query type -> ordered list of (provider, model) to try, best-fit first.
# Cheapest/fastest model wins for SIMPLE; strongest reasoning models win for
# CODE/COMPLEX; largest context window wins for LONG_CONTEXT.
ROUTE_TABLE: dict[QueryType, list[tuple[str, str]]] = {
    QueryType.SIMPLE: [
        ("openai", "gpt-4o-mini"),
        ("gemini", "gemini-2.0-flash"),
        ("anthropic", "claude-haiku-4-5-20251001"),
    ],
    QueryType.CODE: [
        ("anthropic", "claude-sonnet-4-5-20250929"),
        ("openai", "gpt-4o"),
        ("gemini", "gemini-1.5-pro"),
    ],
    QueryType.COMPLEX: [
        ("anthropic", "claude-sonnet-4-5-20250929"),
        ("openai", "gpt-4o"),
        ("gemini", "gemini-1.5-pro"),
    ],
    QueryType.LONG_CONTEXT: [
        ("gemini", "gemini-1.5-pro"),
        ("anthropic", "claude-sonnet-4-5-20250929"),
        ("openai", "gpt-4o"),
    ],
}


@dataclass
class RouteDecision:
    classification: Classification
    chain: list[tuple[str, str]]  # ordered [(provider, model), ...] to attempt


def decide_route(prompt: str, override_model: str | None = None) -> RouteDecision:
    """
    override_model lets a client pin a specific model (bypassing routing
    logic) while still going through the same fallback/cache/logging
    pipeline — used by the chat UI's manual model picker.
    """
    classification = classify(prompt)

    if override_model:
        provider = MODEL_PROVIDER_MAP.get(override_model)
        if provider is None:
            raise ValueError(f"Unknown model: {override_model}")
        chain = [(provider, override_model)]
        # still append the normal chain as fallback in case the pinned model's
        # provider is down
        chain += [pm for pm in ROUTE_TABLE[classification.query_type] if pm[1] != override_model]
        return RouteDecision(classification=classification, chain=chain)

    return RouteDecision(classification=classification, chain=ROUTE_TABLE[classification.query_type])
