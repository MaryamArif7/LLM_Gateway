from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import BaseProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAIProvider

_PROVIDER_CLASSES: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}


def get_provider(name: str, api_key: str) -> BaseProvider:
    """
    BYOK means there's no longer one shared client per provider — every
    call needs to be built with the specific user's own key. This makes a
    fresh, lightweight client per call rather than caching a singleton,
    since the key differs by user. If this ever shows up in profiling,
    the next step is a small LRU cache keyed on (name, api_key).
    """
    provider_class = _PROVIDER_CLASSES.get(name)
    if provider_class is None:
        raise ValueError(f"Unknown provider: {name}")
    return provider_class(api_key)



MODEL_PROVIDER_MAP = {
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "claude-sonnet-4-5-20250929": "anthropic",
    "claude-haiku-4-5-20251001": "anthropic",
    "gemini-2.0-flash": "gemini",
    "gemini-1.5-pro": "gemini",
}
