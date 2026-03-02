from __future__ import annotations

from typing import List, Tuple

import httpx
from openai import OpenAI

from config import get_settings


settings = get_settings()


class ChatService:
    def _normalize_provider(self, provider: str) -> str:
        normalized = (provider or "openai").strip().lower()
        if normalized not in {"openai", "gemini", "claude"}:
            raise ValueError(f"Unsupported provider: {provider}")
        return normalized

    def _messages_to_text(self, system_prompt: str, messages: List[Tuple[str, str]]) -> str:
        chunks = [f"System:\n{system_prompt.strip()}"]
        for role, content in messages:
            chunks.append(f"{role.capitalize()}:\n{content.strip()}")
        chunks.append("Assistant:")
        return "\n\n".join(chunks).strip()

    def chat(
        self,
        system_prompt: str,
        messages: List[Tuple[str, str]],
        *,
        provider: str = "openai",
        api_key: str | None = None,
        model: str | None = None,
    ) -> str:
        normalized_provider = self._normalize_provider(provider)
        key = api_key or settings.openai_api_key
        if not key:
            raise RuntimeError("Missing API key for BYOK execution")

        if normalized_provider == "openai":
            client = OpenAI(api_key=key)
            target_model = model or settings.openai_chat_model
            chat_messages = [{"role": "system", "content": system_prompt}]
            for role, content in messages:
                chat_messages.append({"role": role, "content": content})

            resp = client.chat.completions.create(
                model=target_model,
                messages=chat_messages,
            )
            choice = resp.choices[0]
            return choice.message.content or ""

        if normalized_provider == "gemini":
            target_model = model or settings.gemini_chat_model
            prompt = self._messages_to_text(system_prompt, messages)
            resp = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent",
                params={"key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2},
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            body = resp.json()
            candidates = body.get("candidates") or []
            if not candidates:
                return ""
            parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
            text_parts = [p.get("text", "") for p in parts if isinstance(p, dict)]
            return "\n".join(part for part in text_parts if part).strip()

        # claude
        target_model = model or settings.claude_chat_model
        prompt = self._messages_to_text(system_prompt, messages)
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": target_model,
                "system": system_prompt,
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        body = resp.json()
        content = body.get("content") or []
        text_parts = [
            item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "\n".join(part for part in text_parts if part).strip()


chat_service = ChatService()
