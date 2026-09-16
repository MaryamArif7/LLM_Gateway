
from dataclasses import dataclass

from app.providers import MODEL_PROVIDER_MAP
from app.router.classifier import Classification, QueryType, classify


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
    chain: list[tuple[str, str]]  


def decide_route(prompt: str, override_model: str | None = None) -> RouteDecision:
    classification = classify(prompt)

    if override_model:
        provider = MODEL_PROVIDER_MAP.get(override_model)
        if provider is None:
            raise ValueError(f"Unknown model: {override_model}")
        chain = [(provider, override_model)]
        chain += [pm for pm in ROUTE_TABLE[classification.query_type] if pm[1] != override_model]
        return RouteDecision(classification=classification, chain=chain)

    return RouteDecision(classification=classification, chain=ROUTE_TABLE[classification.query_type])
