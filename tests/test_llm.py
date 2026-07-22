"""M5 LLM provider tests.

All deterministic and network-free: the stub for behaviour and retry, an
injected fake transport for the two hosted providers, and the factory for config
selection.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.llm import (
    LLMError,
    LLMProvider,
    ProviderConfig,
    RetryPolicy,
    compute_backoff,
    get_provider,
)
from app.llm.ollama import OllamaProvider
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.stub import StubProvider


def _no_sleep(_delay: float) -> None:
    """A no-op sleep so retry tests do not actually wait."""


def test_stub_echoes_prompt_by_default() -> None:
    provider = StubProvider()
    assert provider.complete("preserve ⟦PA⟧ exactly") == "preserve ⟦PA⟧ exactly"


def test_stub_replays_scripted_responses_in_order() -> None:
    provider = StubProvider(scripted=["first", "second"])
    assert provider.complete("a") == "first"
    assert provider.complete("b") == "second"
    # Exhausted script falls back to echo.
    assert provider.complete("c") == "c"


def test_stub_scripted_mapping_and_default() -> None:
    provider = StubProvider(scripted={"hello": "world"}, default_response="fallback")
    assert provider.complete("hello") == "world"
    assert provider.complete("anything else") == "fallback"


def test_stub_records_token_usage() -> None:
    provider = StubProvider(default_response="one two three")
    provider.complete("alpha beta", system="sys word")
    assert provider.usage.calls == 1
    assert provider.usage.prompt_tokens == 4  # "alpha beta" (2) + "sys word" (2)
    assert provider.usage.completion_tokens == 3  # "one two three"
    assert provider.usage.total_tokens == 7


def test_retry_succeeds_after_transient_failures() -> None:
    provider = StubProvider(fail_times=2, retry_policy=RetryPolicy(max_attempts=3), sleep=_no_sleep)
    assert provider.complete("go") == "go"
    assert provider.attempts == 3  # two failures then a success
    assert provider.usage.calls == 1  # usage counts successful completions only


def test_retry_exhausts_and_raises() -> None:
    provider = StubProvider(fail_times=5, retry_policy=RetryPolicy(max_attempts=3), sleep=_no_sleep)
    with pytest.raises(LLMError):
        provider.complete("go")
    assert provider.attempts == 3
    assert provider.usage.calls == 0


def test_backoff_schedule_is_increasing_and_capped() -> None:
    policy = RetryPolicy(base_delay=0.5, backoff=2.0, max_delay=8.0)
    assert compute_backoff(policy, 1) == pytest.approx(0.5)
    assert compute_backoff(policy, 2) == pytest.approx(1.0)
    assert compute_backoff(policy, 3) == pytest.approx(2.0)
    assert compute_backoff(policy, 20) == pytest.approx(8.0)  # capped

    # The provider actually sleeps on that schedule between attempts.
    sleeps: list[float] = []
    provider = StubProvider(
        fail_times=2, retry_policy=RetryPolicy(max_attempts=3), sleep=sleeps.append
    )
    provider.complete("go")
    assert sleeps == [pytest.approx(0.5), pytest.approx(1.0)]


def test_openai_compat_shapes_request_and_parses() -> None:
    captured: dict[str, Any] = {}

    def fake_transport(url: str, payload: dict, headers: dict, timeout: float) -> dict:
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        captured["timeout"] = timeout
        return {
            "choices": [{"message": {"content": "REWRITTEN"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3},
        }

    provider = OpenAICompatProvider(
        "qwen-72b",
        base_url="https://api.example.com/v1",
        api_key="secret",
        transport=fake_transport,
        timeout=12.0,
    )
    out = provider.complete("rewrite this", system="you are an editor", temperature=0.2)

    assert out == "REWRITTEN"
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["payload"]["model"] == "qwen-72b"
    assert captured["payload"]["messages"] == [
        {"role": "system", "content": "you are an editor"},
        {"role": "user", "content": "rewrite this"},
    ]
    assert captured["payload"]["temperature"] == 0.2
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["timeout"] == 12.0
    assert provider.usage.prompt_tokens == 11
    assert provider.usage.completion_tokens == 3
    assert provider.usage.total_tokens == 14


def test_openai_compat_raises_on_malformed_response() -> None:
    provider = OpenAICompatProvider(
        "m", base_url="https://x/v1", transport=lambda *a: {"unexpected": True}
    )
    with pytest.raises(LLMError):
        provider.complete("hi")


def test_ollama_shapes_request_and_parses() -> None:
    captured: dict[str, Any] = {}

    def fake_transport(url: str, payload: dict, headers: dict, timeout: float) -> dict:
        captured["url"] = url
        captured["payload"] = payload
        return {"response": "OUT", "prompt_eval_count": 7, "eval_count": 2}

    provider = OllamaProvider("qwen3", transport=fake_transport)
    assert provider.complete("hi", system="s") == "OUT"
    assert captured["url"].endswith("/api/generate")
    assert captured["payload"]["model"] == "qwen3"
    assert captured["payload"]["system"] == "s"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["think"] is False  # thinking off by default
    assert provider.usage.total_tokens == 9


def test_ollama_strips_thinking_from_output() -> None:
    def fake_transport(url: str, payload: dict, headers: dict, timeout: float) -> dict:
        return {
            "response": "<think>Let me plan the rewrite.</think>\n\nThe clean prose.",
            "prompt_eval_count": 5,
            "eval_count": 4,
        }

    provider = OllamaProvider("qwen3", transport=fake_transport)
    # Only the final prose survives; the chain of thought is gone.
    assert provider.complete("rewrite this") == "The clean prose."


def test_factory_selects_stub_and_satisfies_protocol() -> None:
    provider = get_provider(ProviderConfig(kind="stub", extra={"default_response": "ok"}))
    assert isinstance(provider, LLMProvider)  # runtime_checkable protocol
    assert provider.name == "stub"
    assert provider.complete("anything") == "ok"


def test_factory_builds_hosted_providers_without_network() -> None:
    provider = get_provider(
        ProviderConfig(
            kind="together",
            model="qwen-72b",
            base_url="https://api.together.xyz/v1",
            api_key="k",
        )
    )
    assert provider.name == "openai_compat"
    assert provider.retry_policy.max_attempts == 3


def test_factory_rejects_unknown_kind_and_missing_base_url() -> None:
    with pytest.raises(ValueError):
        get_provider(ProviderConfig(kind="nope"))
    with pytest.raises(ValueError):
        get_provider(ProviderConfig(kind="fireworks", model="m"))  # no base_url
