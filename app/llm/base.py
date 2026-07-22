"""Provider contract plus the shared machinery every provider needs.

A provider does one job: turn a prompt into text. But doing it against a real
endpoint means transient failures, timeouts, and token bills, and none of that
should be reimplemented per provider. So the retry-with-backoff loop, the
timeout, and the token accounting live here in one place, and each concrete
provider only implements the single network round trip (`_complete`).

The retry loop is a pure function of an injectable sleep and a fake failure
sequence, so it is exhaustively testable with zero network.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Any provider failure. Retryable by default."""


class LLMTimeoutError(LLMError):
    """A call exceeded its timeout. A subclass so callers can single it out."""


@dataclass
class TokenUsage:
    """Running token count for a provider instance.

    Mutable and per-instance: the orchestrator reads it after a run to build the
    cost line of the audit trail.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.calls += 1


@dataclass(frozen=True)
class RawCompletion:
    """One provider round trip: the text plus what it cost.

    Concrete providers return this from `_complete`; the base class strips it to
    the plain string the protocol promises and folds the token counts into
    usage.
    """

    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff, deterministic (no jitter, so tests can assert it)."""

    max_attempts: int = 3
    base_delay: float = 0.5
    backoff: float = 2.0
    max_delay: float = 8.0


def compute_backoff(policy: RetryPolicy, attempt: int) -> float:
    """Delay before retry `attempt` (1-based), capped at `max_delay`."""

    delay = policy.base_delay * (policy.backoff ** (attempt - 1))
    return min(policy.max_delay, delay)


def call_with_retry(
    fn: Callable[[], RawCompletion],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], None],
    retryable: tuple[type[BaseException], ...] = (LLMError,),
) -> RawCompletion:
    """Call `fn`, retrying on a retryable error with exponential backoff.

    Raises the last error once attempts are exhausted. A non-retryable exception
    propagates immediately: a bug in prompt assembly should not be retried.
    """

    last: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except retryable as exc:
            last = exc
            if attempt >= policy.max_attempts:
                break
            delay = compute_backoff(policy, attempt)
            logger.warning(
                "llm call failed (attempt %d/%d): %s; retrying in %.2fs",
                attempt,
                policy.max_attempts,
                exc,
                delay,
            )
            sleep(delay)
    assert last is not None  # the loop only breaks after catching an exception
    raise last


# A transport is the one impure step: send a JSON payload, get JSON back. Making
# it injectable lets the network providers be tested with a fake, no sockets.
Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def urllib_transport(
    url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float
) -> dict[str, Any]:
    """Default transport: a plain POST of JSON via the standard library.

    Zero third-party dependencies on purpose. Network and decode failures are
    wrapped as LLMError (or LLMTimeoutError) so the retry loop can act on them.
    """

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except TimeoutError as exc:
        raise LLMTimeoutError(f"request to {url} timed out after {timeout}s") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError):
            raise LLMTimeoutError(f"request to {url} timed out") from exc
        raise LLMError(f"transport error calling {url}: {reason}") from exc
    try:
        parsed: dict[str, Any] = json.loads(body)
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON from {url}") from exc
    return parsed


@runtime_checkable
class LLMProvider(Protocol):
    """The contract everything above `app/llm/` depends on.

    `complete` takes the user prompt and an optional system prompt, plus
    provider-specific options, and returns generated text. `usage` accumulates
    token counts across calls.
    """

    name: str
    usage: TokenUsage

    def complete(self, prompt: str, system: str | None = None, **opts: Any) -> str: ...


class RetryingProvider:
    """Base class carrying retry, timeout, and token accounting.

    Subclasses implement only `_complete`, the single network round trip.
    """

    name = "base"

    def __init__(
        self,
        *,
        retry_policy: RetryPolicy | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.retry_policy = retry_policy or RetryPolicy()
        self.timeout = timeout
        self._sleep = sleep
        self.usage = TokenUsage()

    def complete(self, prompt: str, system: str | None = None, **opts: Any) -> str:
        raw = call_with_retry(
            lambda: self._complete(prompt, system, **opts),
            self.retry_policy,
            sleep=self._sleep,
        )
        self.usage.add(raw.prompt_tokens, raw.completion_tokens)
        return raw.text

    def _complete(self, prompt: str, system: str | None, **opts: Any) -> RawCompletion:
        raise NotImplementedError
