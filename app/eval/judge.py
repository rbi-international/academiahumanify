"""LLM-as-judge: a strong model reads the rewrites and picks the best.

The deterministic harness in evaluate.py measures tells and drift, but it cannot
tell you which rewrite actually reads best to a careful editor. That is a
judgement call, so we ask a capable model to make it. The judge ranks on
faithfulness first, then human readability, then clarity. It is a second opinion
on prose quality, not a detector: it never sees or optimises a detection score.

The judge is provider-agnostic. Pass any LLMProvider (a premium hosted model in
production, the stub in tests). Its verdict is advisory, sitting alongside the
deterministic ranking, never overriding the fidelity gate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.llm.base import LLMError, LLMProvider
from app.prompts import PromptRegistry, default_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JudgeVerdict:
    """The judge's call, parsed from its reply.

    `best_label` is None when the reply could not be parsed, so a judge failure
    degrades to "no opinion" rather than crashing the comparison.
    """

    best_label: str | None
    ranking: tuple[str, ...]
    rationale: dict[str, str]
    raw: str

    @property
    def ok(self) -> bool:
        return self.best_label is not None


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of the model's reply.

    Models sometimes wrap JSON in prose or fences despite instructions, so we
    take the span from the first brace to the last and try to parse it.
    """

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def judge_rewrites(
    original: str,
    rewrites: dict[str, str],
    provider: LLMProvider,
    *,
    registry: PromptRegistry | None = None,
) -> JudgeVerdict:
    """Ask `provider` to rank labelled rewrites of `original`.

    `rewrites` maps a label (a model id, or A/B/C) to the rewritten text. The
    returned verdict uses only labels that were supplied; unknown labels in the
    reply are dropped.
    """

    labels = list(rewrites)
    reg = registry or default_registry()
    system = reg.get("system/judge").text

    parts = [f"ORIGINAL:\n{original.strip()}\n", "REWRITES:"]
    for label, text in rewrites.items():
        parts.append(f"\n[{label}]\n{text.strip()}")
    user = "\n".join(parts)

    try:
        reply = provider.complete(user, system=system)
    except LLMError as exc:
        logger.warning("judge provider failed: %s", exc)
        return JudgeVerdict(best_label=None, ranking=(), rationale={}, raw=str(exc))

    parsed = _extract_json(reply)
    if parsed is None:
        logger.warning("judge reply was not parseable JSON")
        return JudgeVerdict(best_label=None, ranking=(), rationale={}, raw=reply)

    known = set(labels)
    ranking = tuple(str(x) for x in parsed.get("ranking", []) if str(x) in known)
    rationale = {
        str(k): str(v) for k, v in dict(parsed.get("rationale", {})).items() if str(k) in known
    }
    best = parsed.get("best")
    best_label = str(best) if best is not None and str(best) in known else None
    # Fall back to the head of a valid ranking if best was missing or unknown.
    if best_label is None and ranking:
        best_label = ranking[0]

    return JudgeVerdict(best_label=best_label, ranking=ranking, rationale=rationale, raw=reply)
