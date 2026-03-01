import os
from functools import lru_cache

from pydantic import BaseSettings, AnyHttpUrl


class Settings(BaseSettings):
    app_name: str = "Aura API"

    frontend_url: AnyHttpUrl | None = None

    database_url: str = os.getenv("DATABASE_URL", "")

    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_oauth_redirect_uri: str = os.getenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "http://localhost:8000/auth/google/callback",
    )

    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "CHANGE_ME_IN_PROD")
    jwt_algorithm: str = "HS256"
    access_token_expires_minutes: int = 60

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()

