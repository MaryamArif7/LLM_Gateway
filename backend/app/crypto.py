"""
Two different secrets live in this app, and they need two different
treatments.

Gateway API keys (what a user pastes into the chat client to call OUR
service) are hashed one-way with SHA-256, the same way a password would be.
We never need the original value back, we only need to check "does this
hash match a row in the database", so hashing is enough and it's simpler
and safer than encryption for this case.

Provider keys (a user's own OpenAI / Anthropic / Gemini / Mistral key) are
different: we DO need the original value back, because we have to hand it
to the OpenAI SDK on every request. That means we can't hash it, we have
to encrypt it so it can be decrypted later, using a secret only this
server knows (ENCRYPTION_KEY in .env).
"""
import hashlib
import secrets

from cryptography.fernet import Fernet

from app.config import settings

_fernet = Fernet(settings.ENCRYPTION_KEY.encode())


def generate_gateway_key() -> str:
    """A random, unguessable key shown to the user exactly once."""
    return f"gw_{secrets.token_urlsafe(32)}"


def hash_gateway_key(raw_key: str) -> str:
    """One-way hash — stored in the database instead of the raw key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def encrypt_provider_key(raw_key: str) -> str:
    """Reversible — used for provider keys, which we need back later."""
    return _fernet.encrypt(raw_key.encode()).decode()


def decrypt_provider_key(encrypted_key: str) -> str:
    return _fernet.decrypt(encrypted_key.encode()).decode()


def mask_key(raw_key: str) -> str:
    """Last 4 characters only, for display in the dashboard."""
    return f"...{raw_key[-4:]}" if len(raw_key) >= 4 else "...."
