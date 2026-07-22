"""Config-driven provider selection.

This is the only place that names concrete providers, and it imports them lazily
inside the factory. Nothing above `app/llm/` imports a provider class directly;
they call `get_provider(config)` and receive something that satisfies the
LLMProvider protocol. Swapping models is a config change, not a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.llm.base import LLMProvider, RetryPolicy

# Hosted vendors that all speak the OpenAI chat-completions schema.
_OPENAI_COMPATIBLE = frozenset(
    {"openai_compat", "together", "fireworks", "deepinfra", "groq"}
)


@dataclass(frozen=True)
class ProviderConfig:
    """Everything needed to build a provider, and nothing model-specific leaks
    above this layer."""

    kind: str
    model: str = ""
    base_url: str | None = None
    api_key: str | None = None
    host: str = "http://localhost:11434"
    timeout: float = 30.0
    max_attempts: int = 3
    # Provider-construction extras (for example the stub's scripted responses).
    extra: dict[str, Any] = field(default_factory=dict)


def get_provider(config: ProviderConfig) -> LLMProvider:
    """Build the provider named by `config.kind`.

    Imports are local so the concrete provider modules are pulled in only when
    selected, keeping the one-way dependency clean.
    """

    policy = RetryPolicy(max_attempts=config.max_attempts)

    if config.kind == "stub":
        from app.llm.stub import StubProvider

        return StubProvider(retry_policy=policy, timeout=config.timeout, **config.extra)

    if config.kind == "ollama":
        from app.llm.ollama import OllamaProvider

        return OllamaProvider(
            config.model, host=config.host, retry_policy=policy, timeout=config.timeout
        )

    if config.kind in _OPENAI_COMPATIBLE:
        if not config.base_url:
            raise ValueError(f"provider kind {config.kind!r} requires base_url")
        from app.llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            config.model,
            base_url=config.base_url,
            api_key=config.api_key,
            retry_policy=policy,
            timeout=config.timeout,
        )

    raise ValueError(f"unknown provider kind: {config.kind!r}")
