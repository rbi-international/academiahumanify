"""Deterministic stub provider: the whole pipeline testable with zero network.

The stub never touches a model. By default it echoes the prompt back unchanged,
which is exactly what the rewrite path wants under test: if the prompt carries
protected placeholders, an identity echo returns them intact, so the integrity
checks exercise real behaviour without a live model.

It can also replay scripted responses (to simulate a specific rewrite) and fail
a fixed number of times before succeeding (to exercise the retry loop). Token
counts are a simple word count, deterministic and good enough for accounting
tests.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from app.llm.base import LLMError, RawCompletion, RetryingProvider


def _estimate_tokens(text: str) -> int:
    return len(text.split())


class StubProvider(RetryingProvider):
    """A canned, deterministic provider.

    Args:
        default_response: returned for every prompt (overrides echo).
        scripted: a mapping prompt -> response, or a sequence consumed in order.
        fail_times: raise on the first N attempts, then behave normally. Used to
            drive the retry loop in tests.
        error_factory: builds the exception raised while failing.
    """

    name = "stub"

    def __init__(
        self,
        *,
        default_response: str | None = None,
        scripted: dict[str, str] | Sequence[str] | None = None,
        fail_times: int = 0,
        error_factory: Callable[[], BaseException] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._default = default_response
        self._scripted = scripted
        self._fail_times = fail_times
        self._error_factory = error_factory or (lambda: LLMError("stub induced failure"))
        # Every _complete call, success or failure, so retry tests can assert it.
        self.attempts = 0
        self._seq_index = 0

    def _resolve(self, prompt: str) -> str:
        if isinstance(self._scripted, dict):
            text = self._scripted.get(prompt)
            if text is not None:
                return text
        elif self._scripted is not None:
            if self._seq_index < len(self._scripted):
                text = self._scripted[self._seq_index]
                self._seq_index += 1
                return text
        if self._default is not None:
            return self._default
        return prompt  # echo

    def _complete(self, prompt: str, system: str | None, **opts: Any) -> RawCompletion:
        self.attempts += 1
        if self.attempts <= self._fail_times:
            raise self._error_factory()
        text = self._resolve(prompt)
        return RawCompletion(
            text=text,
            prompt_tokens=_estimate_tokens(prompt) + _estimate_tokens(system or ""),
            completion_tokens=_estimate_tokens(text),
        )
