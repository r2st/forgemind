"""Encryption utilities for storing API keys."""

from cryptography.fernet import Fernet
from .config import get_settings


def get_cipher() -> Fernet:
    """Get Fernet cipher for encryption/decryption."""
    settings = get_settings()
    # gateway_secret_key is now validated/generated in config.py, so it's always set
    return Fernet(settings.gateway_secret_key.encode())


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key."""
    if not api_key:
        return ""
    cipher = get_cipher()
    return cipher.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted: str) -> str:
    """Decrypt an API key."""
    if not encrypted:
        return ""
    cipher = get_cipher()
    return cipher.decrypt(encrypted.encode()).decode()


def mask_api_key(api_key: str) -> str:
    """Mask an API key for display."""
    if not api_key:
        return ""
    if len(api_key) <= 10:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"
