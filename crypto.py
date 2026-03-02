from functools import lru_cache

from cryptography.fernet import Fernet
from fastapi import HTTPException, status

from config import get_settings


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    settings = get_settings()
    try:
        return Fernet(settings.encryption_key.encode())
    except Exception:
        raise ValueError("Invalid ENCRYPTION_KEY format.")


def encrypt_api_key(api_key: str) -> str:
    f = get_fernet()
    return f.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    f = get_fernet()
    try:
        return f.decrypt(encrypted_key.encode()).decode()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt API key."
        )
