"""Ollama provider: a local small Qwen3 for development.

Talks to the Ollama HTTP API on localhost. Not exercised in CI (it needs a
running daemon), but the request shaping and response parsing are testable
through an injected transport.

Qwen3 and other hybrid models emit their chain of thought wrapped in <think>
tags, and for a rewrite we want only the final prose. We ask the daemon to turn
thinking off, and we strip any <think> block that slips through anyway, so the
output is as clean as a hosted chat model's.
"""

from __future__ import annotations

import re
from typing import Any

from app.llm.base import LLMError, RawCompletion, RetryingProvider, Transport, urllib_transport

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)


class OllamaProvider(RetryingProvider):
    name = "ollama"

    def __init__(
        self,
        model: str,
        *,
        host: str = "http://localhost:11434",
        think: bool = False,
        strip_think: bool = True,
        transport: Transport | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.model = model
        self.host = host.rstrip("/")
        self.think = think
        self.strip_think = strip_think
        self._transport = transport or urllib_transport

    def _complete(self, prompt: str, system: str | None, **opts: Any) -> RawCompletion:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            # Ask capable models to skip thinking; ignored by models without it.
            "think": self.think,
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

        if self.strip_think:
            # Belt and braces: remove any thinking that leaked into the text.
            text = _THINK_BLOCK.sub("", text).lstrip()

        return RawCompletion(
            text=text,
            prompt_tokens=int(data.get("prompt_eval_count", 0)),
            completion_tokens=int(data.get("eval_count", 0)),
        )
