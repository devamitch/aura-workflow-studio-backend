from __future__ import annotations

from functools import lru_cache
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Aura AI API"
    environment: Literal["local", "development", "staging", "production"] = "development"
    debug: bool = False

    database_url: str = "sqlite:///./aura.db"
    frontend_url: str | None = None

    # CORS + Host hardening
    cors_allow_origins: List[str] = Field(
        default_factory=lambda: [
            "https://devamit.co.in",
            "http://localhost:3000",
        ]
    )
    cors_allow_origin_regex: str = r"^https:\/\/([a-z0-9-]+\.)*devamit\.co\.in$"
    trusted_hosts: List[str] = Field(
        default_factory=lambda: [
            "devamit.co.in",
            "*.devamit.co.in",
            "*.onrender.com",
            "localhost",
            "127.0.0.1",
        ]
    )
    force_https_redirect: bool = False

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # Supabase JWT verification (recommended if frontend signs in via Supabase)
    supabase_jwt_secret: str | None = None

    # JWT Authentication
    jwt_secret_key: str = "change_me_in_production"
    jwt_algorithm: str = "HS256"
    access_token_expires_minutes: int = 1440

    # BYOK Encryption
    encryption_key: str = "X2jO2eU1Q6UqQcYwZzT_8Q9S-7W9fO1P9L1D3G8R_5g="

    # Provider defaults for BYOK execution
    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    gemini_chat_model: str = "gemini-1.5-flash"
    gemini_embedding_model: str = "text-embedding-004"

    claude_chat_model: str = "claude-3-5-sonnet-latest"

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug(cls, value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
                return False
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
