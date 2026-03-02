from __future__ import annotations

from typing import List

import httpx
from openai import OpenAI

from config import get_settings


settings = get_settings()


class EmbeddingService:
    def _normalize_provider(self, provider: str) -> str:
        normalized = (provider or "openai").strip().lower()
        if normalized not in {"openai", "gemini", "claude"}:
            raise ValueError(f"Unsupported provider: {provider}")
        return normalized

    def embed_text(
        self,
        text: str,
        *,
        provider: str = "openai",
        api_key: str | None = None,
        model: str | None = None,
    ) -> List[float]:
        text = text.strip()
        if not text:
            return []

        normalized_provider = self._normalize_provider(provider)
        key = api_key or settings.openai_api_key
        if not key:
            raise RuntimeError("Missing API key for BYOK embeddings")

        if normalized_provider == "openai":
            client = OpenAI(api_key=key)
            target_model = model or settings.openai_embedding_model
            resp = client.embeddings.create(model=target_model, input=text)
            return resp.data[0].embedding  # type: ignore[no-any-return]

        if normalized_provider == "gemini":
            target_model = model or settings.gemini_embedding_model
            resp = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:embedContent",
                params={"key": key},
                json={"content": {"parts": [{"text": text}]}},
                timeout=30.0,
            )
            resp.raise_for_status()
            body = resp.json()
            values = (((body.get("embedding") or {}).get("values")) or [])
            return [float(v) for v in values]

        raise ValueError("Claude does not support embeddings in this backend profile")


embedding_service = EmbeddingService()
