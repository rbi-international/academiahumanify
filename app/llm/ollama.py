"""Ollama provider: a local small Qwen3 for development.

Talks to the Ollama HTTP API on localhost. Not exercised in CI (it needs a
running daemon), but the request shaping and response parsing are testable
through an injected transport.
"""

from __future__ import annotations

from typing import Any

from app.llm.base import LLMError, RawCompletion, RetryingProvider, Transport, urllib_transport


class OllamaProvider(RetryingProvider):
    name = "ollama"

    def __init__(
        self,
        model: str,
        *,
        host: str = "http://localhost:11434",
        transport: Transport | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.model = model
        self.host = host.rstrip("/")
        self._transport = transport or urllib_transport

    def _complete(self, prompt: str, system: str | None, **opts: Any) -> RawCompletion:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system
        if opts:
            payload["options"] = opts

        data = self._transport(f"{self.host}/api/generate", payload, {}, self.timeout)
        try:
            text = data["response"]
        except (KeyError, TypeError) as exc:
            raise LLMError("ollama response missing 'response' field") from exc

        return RawCompletion(
            text=text,
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
        )
