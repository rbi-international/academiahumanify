"""OpenAI-compatible provider for hosted endpoints.

Together, Fireworks, DeepInfra, and Groq all expose the same chat-completions
schema, so one provider covers them all; only the base URL and API key change.
The request shaping and response parsing are testable through an injected
transport, no network required.
"""

from __future__ import annotations

from typing import Any

from app.llm.base import LLMError, RawCompletion, RetryingProvider, Transport, urllib_transport


class OpenAICompatProvider(RetryingProvider):
    name = "openai_compat"

    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str | None = None,
        transport: Transport | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._transport = transport or urllib_transport

    def _complete(self, prompt: str, system: str | None, **opts: Any) -> RawCompletion:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {"model": self.model, "messages": messages, **opts}
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = self._transport(f"{self.base_url}/chat/completions", payload, headers, self.timeout)
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("malformed chat-completions response") from exc

        usage = data.get("usage") or {}
        return RawCompletion(
            text=text,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
        )
