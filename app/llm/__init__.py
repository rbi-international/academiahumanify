"""LLM provider layer.

Everything above this package is model-agnostic. Callers never import a concrete
provider; they build one from config through `get_provider`. That single seam is
what lets the production model swap from a local Qwen3 to a hosted 72B endpoint,
or to the deterministic stub in tests, without a line changing upstream.
"""

from __future__ import annotations

from app.llm.base import (
    LLMError,
    LLMProvider,
    LLMTimeoutError,
    RawCompletion,
    RetryPolicy,
    TokenUsage,
    compute_backoff,
)
from app.llm.factory import ProviderConfig, get_provider

__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMTimeoutError",
    "ProviderConfig",
    "RawCompletion",
    "RetryPolicy",
    "TokenUsage",
    "compute_backoff",
    "get_provider",
]
