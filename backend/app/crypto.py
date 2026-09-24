import hashlib
import secrets

from cryptography.fernet import Fernet

from app.config import settings

_fernet = Fernet(settings.ENCRYPTION_KEY.encode())


def generate_gateway_key() -> str:
    return f"gw_{secrets.token_urlsafe(32)}"


def hash_gateway_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def encrypt_provider_key(raw_key: str) -> str:
    return _fernet.encrypt(raw_key.encode()).decode()


def decrypt_provider_key(encrypted_key: str) -> str:
    return _fernet.decrypt(encrypted_key.encode()).decode()


def mask_key(raw_key: str) -> str:
    return f"...{raw_key[-4:]}" if len(raw_key) >= 4 else "...."
