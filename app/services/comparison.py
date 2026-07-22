"""Comparison service: rewrite one draft with many models, then rank the results.

This is the feature the user picks from: choose some models, get every rewrite
back with a full scorecard, and see which one wins. The ranking rule is settled:
fidelity is a hard gate, and quality ranks the survivors. A rewrite that changed
a fact can never be "best", however well it reads.

Two design commitments make this last:

- Failure isolation. One model erroring (a network blip, an integrity hard-fail,
  a missing key) marks that one candidate failed with its reason. The rest still
  come back. A comparison is never all-or-nothing.
- Reproducibility. Every candidate records its model id, the prompt refs with
  checksums, and its token cost, and the whole comparison serialises to a plain
  dict, so a result can be stored and re-read years later.

The models run concurrently under a worker cap. The evaluation is deterministic.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from app.eval import Evaluation, evaluate
from app.llm.base import LLMProvider
from app.llm.catalog import ModelCatalog, default_catalog
from app.llm.factory import get_provider
from app.pipeline.base import Document, RunContext
from app.pipeline.rewrite import RewriteStage
from app.pipeline.segment import Segmenter
from app.pipeline.stylometry import extract
from app.prompts import Discipline, StyleVariant

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    """One model's attempt at the draft, with its scorecard."""

    model_id: str
    display_name: str
    ok: bool  # ran to completion without a hard failure
    error: str | None
    rewritten_text: str | None
    evaluation: Evaluation | None
    eligible: bool  # passed the fidelity gate
    tokens: int
    prompt_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "ok": self.ok,
            "error": self.error,
            "eligible": self.eligible,
            "tokens": self.tokens,
            "prompt_refs": list(self.prompt_refs),
            "rewritten_text": self.rewritten_text,
            "evaluation": self.evaluation.to_dict() if self.evaluation else None,
        }


@dataclass(frozen=True)
class Comparison:
    """A ranked set of candidates for one draft."""

    original_text: str
    candidates: tuple[Candidate, ...]

    def best(self) -> Candidate | None:
        """The top-ranked fidelity-passing candidate, or None if none qualified."""
        top = self.candidates[0] if self.candidates else None
        return top if top and top.eligible else None

    def to_dict(self) -> dict[str, Any]:
        best = self.best()
        return {
            "original_text": self.original_text,
            "best": best.model_id if best else None,
            "candidates": [c.to_dict() for c in self.candidates],
        }


def _rank_key(candidate: Candidate) -> tuple[int, float]:
    """Sort eligible first (by quality, best first), then ran-but-failed-gate,
    then errored. Ties fall back to model id for a stable order."""
    if not candidate.ok or candidate.evaluation is None:
        return (2, 0.0)
    if not candidate.eligible:
        return (1, -candidate.evaluation.quality_rank)
    return (0, -candidate.evaluation.quality_rank)


def _joined(doc: Document) -> str:
    return "\n\n".join(segment.text for segment in doc.segments)


def compare_with_providers(
    text: str,
    providers: dict[str, LLMProvider],
    ctx: RunContext,
    *,
    display_names: dict[str, str] | None = None,
    style: StyleVariant = StyleVariant.MODERN_INTERDISCIPLINARY,
    discipline: Discipline | None = None,
    max_workers: int = 4,
) -> Comparison:
    """Rewrite `text` with each provider and rank the results.

    The core that takes ready-made providers, so it is fully testable with stubs.
    `providers` maps a model id to a provider instance.
    """

    names = display_names or {}
    voice = extract(ctx.voice_sample) if ctx.voice_sample else None

    # Segment once. Every model rewrites the same segmentation.
    base_doc = Segmenter().run(Document(text=text), ctx)
    original_joined = _joined(base_doc)

    def _run(model_id: str, provider: LLMProvider) -> Candidate:
        display = names.get(model_id, model_id)
        try:
            result_doc = RewriteStage(
                provider, style=style, discipline=discipline, max_workers=1
            ).run(base_doc, ctx)
        except Exception as exc:  # failure isolation: one model must not sink the run
            logger.warning("model %s failed: %s", model_id, exc)
            return Candidate(
                model_id=model_id,
                display_name=display,
                ok=False,
                error=str(exc),
                rewritten_text=None,
                evaluation=None,
                eligible=False,
                tokens=provider.usage.total_tokens,
                prompt_refs=(),
            )
        rewritten = _joined(result_doc)
        ev = evaluate(original_joined, rewritten, voice)
        refs = tuple(result_doc.reports[-1].notes.get("prompt_refs", ()))
        return Candidate(
            model_id=model_id,
            display_name=display,
            ok=True,
            error=None,
            rewritten_text=rewritten,
            evaluation=ev,
            eligible=ev.eligible,
            tokens=provider.usage.total_tokens,
            prompt_refs=refs,
        )

    items = list(providers.items())
    if items:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            candidates = list(pool.map(lambda kv: _run(kv[0], kv[1]), items))
    else:
        candidates = []

    candidates.sort(key=_rank_key)
    return Comparison(original_text=original_joined, candidates=tuple(candidates))


def compare(
    text: str,
    model_ids: list[str],
    ctx: RunContext,
    *,
    catalog: ModelCatalog | None = None,
    style: StyleVariant = StyleVariant.MODERN_INTERDISCIPLINARY,
    discipline: Discipline | None = None,
    max_workers: int = 4,
) -> Comparison:
    """Rewrite `text` with the named catalog models and rank the results.

    Models whose key is missing become a failed candidate explaining what to set,
    rather than a hard error, so a partial selection still returns something.
    """

    cat = catalog or default_catalog()
    providers: dict[str, LLMProvider] = {}
    names: dict[str, str] = {}
    unavailable: list[Candidate] = []

    for model_id in model_ids:
        spec = cat.get(model_id)
        names[model_id] = spec.display_name
        if not spec.available():
            unavailable.append(
                Candidate(
                    model_id=model_id,
                    display_name=spec.display_name,
                    ok=False,
                    error=f"unavailable: set {spec.api_key_env} in the environment",
                    rewritten_text=None,
                    evaluation=None,
                    eligible=False,
                    tokens=0,
                    prompt_refs=(),
                )
            )
            continue
        providers[model_id] = get_provider(spec.to_provider_config())

    comparison = compare_with_providers(
        text,
        providers,
        ctx,
        display_names=names,
        style=style,
        discipline=discipline,
        max_workers=max_workers,
    )
    if not unavailable:
        return comparison

    # Fold the unavailable models in, keeping the ranking order (they sort last).
    merged = list(comparison.candidates) + unavailable
    merged.sort(key=_rank_key)
    return Comparison(original_text=comparison.original_text, candidates=tuple(merged))
