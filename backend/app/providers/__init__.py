from app.config import settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import BaseProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAIProvider

_registry: dict[str, BaseProvider] = {}


def get_provider(name: str) -> BaseProvider:
    if name not in _registry:
        if name == "openai":
            _registry[name] = OpenAIProvider(settings.OPENAI_API_KEY)
        elif name == "anthropic":
            _registry[name] = AnthropicProvider(settings.ANTHROPIC_API_KEY)
        elif name == "gemini":
            _registry[name] = GeminiProvider(settings.GEMINI_API_KEY)
        else:
            raise ValueError(f"Unknown provider: {name}")
    return _registry[name]


# model -> provider name, single source of truth for routing/comparison
MODEL_PROVIDER_MAP = {
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "claude-sonnet-4-5-20250929": "anthropic",
    "claude-haiku-4-5-20251001": "anthropic",
    "gemini-2.0-flash": "gemini",
    "gemini-1.5-pro": "gemini",
}
