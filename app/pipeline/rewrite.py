"""M7 rewrite stage: the one place the model actually writes.

This is where generation and protection meet, and the whole design turns on
keeping them apart. For each rewritable segment the deterministic layer masks the
fragile spans, the model rewrites the masked prose, and the deterministic layer
verifies every token survived before anything is restored. The model is never
trusted with a citation or a number.

The rules this stage enforces, from the fidelity invariants:

- Frozen segments (headings, equations, tables, captions, references) never
  reach the model. They pass through byte-identical.
- Methods and Results are forced to CONSERVATIVE intensity regardless of the
  user's setting, because reproducibility outranks flow there.
- A failed integrity check triggers a retry with a corrective instruction, up to
  a hard cap. After that it is a hard failure, never a downgrade to a warning and
  never silently accepted.

Segments are rewritten concurrently under a worker cap (the semaphore) and
reassembled in their original order.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from app.core.protection import ProtectedText, VerificationResult, protect, restore, verify
from app.llm.base import LLMProvider
from app.pipeline.base import (
    Document,
    Intensity,
    RunContext,
    Segment,
    StageReport,
    resolve_intensity,
)
from app.pipeline.stylometry import VoiceProfile, extract
from app.prompts import (
    Discipline,
    PromptRef,
    PromptRegistry,
    StyleVariant,
    compose_rewrite_system,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_WORKERS = 4


class RewriteError(Exception):
    """A segment failed its integrity check after every retry.

    This is a hard failure by design. The protection layer is not allowed to be
    downgraded to a warning, so exhausting the retries raises rather than
    returning corrupted text.
    """


@dataclass(frozen=True)
class _Outcome:
    """Per-segment bookkeeping, aggregated into the stage report afterwards."""

    index: int
    frozen: bool
    attempts: int
    refs: tuple[PromptRef, ...]
    failed: bool = False  # integrity failed after retries; original text kept


class RewriteStage:
    """Rewrite the prose segments of a document, protecting every fragile span.

    The provider is injected, so nothing here knows which model runs. Style and
    discipline are stage configuration; intensity comes per-run from the context
    and is clamped per-section.
    """

    name = "rewrite"

    def __init__(
        self,
        provider: LLMProvider,
        *,
        style: StyleVariant = StyleVariant.MODERN_INTERDISCIPLINARY,
        discipline: Discipline | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        max_workers: int = DEFAULT_MAX_WORKERS,
        registry: PromptRegistry | None = None,
        isolate_failures: bool = False,
    ) -> None:
        self.provider = provider
        self.style = style
        self.discipline = discipline
        self.max_attempts = max_attempts
        self.max_workers = max_workers
        self.registry = registry
        # When True, a segment that cannot pass its integrity check keeps its
        # original text and is flagged, rather than raising. This is fidelity
        # preserving: the bad rewrite is rejected, never accepted. The
        # orchestrator turns this on so one bad segment does not kill a run.
        self.isolate_failures = isolate_failures

    def run(self, doc: Document, ctx: RunContext) -> Document:
        voice = extract(ctx.voice_sample) if ctx.voice_sample else None

        # Concurrency with a worker cap is the semaphore. ThreadPoolExecutor.map
        # preserves input order, so reassembly is ordered for free, and it
        # re-raises a worker's exception when the results are consumed, so a hard
        # integrity failure propagates out of the run.
        if doc.segments:
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                pairs = list(pool.map(lambda seg: self._process(seg, ctx, voice), doc.segments))
        else:
            pairs = []

        new_segments = tuple(seg for seg, _ in pairs)
        outcomes = [outcome for _, outcome in pairs]

        rewritten = sum(1 for o in outcomes if not o.frozen and not o.failed)
        frozen = sum(1 for o in outcomes if o.frozen)
        failed = sum(1 for o in outcomes if o.failed)
        retries = sum(o.attempts - 1 for o in outcomes if not o.frozen)
        refs = _unique_refs(outcomes)

        report = StageReport(
            stage=self.name,
            ok=failed == 0,
            notes={
                "segments": len(outcomes),
                "rewritten": rewritten,
                "frozen": frozen,
                "failed": failed,
                "retries": retries,
                "voice": voice.confidence.value if voice else "none",
                "prompt_refs": [f"{r.id}@v{r.version}:{r.checksum[:8]}" for r in refs],
                "tokens": self.provider.usage.total_tokens,
            },
        )
        return doc.with_segments(new_segments, report)

    def _process(
        self, segment: Segment, ctx: RunContext, voice: VoiceProfile | None
    ) -> tuple[Segment, _Outcome]:
        # Frozen segments never see the model. Byte-identical passthrough.
        if segment.frozen:
            return segment, _Outcome(segment.index, frozen=True, attempts=0, refs=())

        protected = protect(segment.text)
        intensity = resolve_intensity(segment.section, ctx.intensity)
        system, refs = self._system_prompt(intensity, voice)

        try:
            masked_output, attempts = self._generate(protected, system, segment.index)
        except RewriteError:
            if not self.isolate_failures:
                raise
            logger.warning("segment %d kept its original after integrity failure", segment.index)
            return segment, _Outcome(
                segment.index, frozen=False, attempts=self.max_attempts, refs=refs, failed=True
            )
        # Verified inside _generate, so restore is safe here.
        new_text = restore(masked_output, protected.mapping)
        return segment.with_text(new_text), _Outcome(
            segment.index, frozen=False, attempts=attempts, refs=refs
        )

    def _generate(self, protected: ProtectedText, system: str, index: int) -> tuple[str, int]:
        """Call the model, verifying integrity, retrying with a correction.

        Returns the verified masked output and how many attempts it took. Raises
        RewriteError once the attempts are spent.
        """

        user = protected.masked
        last: VerificationResult | None = None
        for attempt in range(1, self.max_attempts + 1):
            output = self.provider.complete(user, system=system)
            result = verify(output, protected)
            if result.ok:
                return output, attempt
            last = result
            logger.warning(
                "segment %d failed integrity on attempt %d/%d: %s",
                index,
                attempt,
                self.max_attempts,
                _describe(result),
            )
            user = _corrective(protected, result)

        raise RewriteError(
            f"segment {index} failed the integrity check after "
            f"{self.max_attempts} attempts: {_describe(last)}"
        )

    def _system_prompt(
        self, intensity: Intensity, voice: VoiceProfile | None
    ) -> tuple[str, tuple[PromptRef, ...]]:
        rendered = compose_rewrite_system(
            intensity, self.style, self.discipline, registry=self.registry
        )
        text = rendered.text
        if voice is not None:
            text = text + "\n\n" + _voice_directive(voice)
        return text, rendered.refs


def _voice_directive(voice: VoiceProfile) -> str:
    """A compact block of the author's measured voice targets plus an exemplar.

    Explicit numbers are followed far more reliably than "match this vibe", so we
    hand the model both the numbers and a paragraph of the author's own prose.
    """

    f = voice.features
    lines = [
        "Match the author's voice. Targets measured from their own writing:",
        f"- sentence length around {f.sentence_length_mean:.0f} words, kept uneven "
        f"(variance around {f.sentence_length_variance:.0f})",
        f"- passive voice in roughly {f.passive_ratio * 100:.0f}% of sentences",
        f"- hedging around {f.hedging_density:.1f} per 100 words",
    ]
    if not voice.reliable:
        lines.append("- the sample is short, so treat these as loose guidance")
    directive = "\n".join(lines)
    return (
        directive
        + "\n\nA paragraph of the author's own writing, for feel:\n"
        + voice.exemplar.strip()
    )


def _corrective(protected: ProtectedText, result: VerificationResult) -> str:
    """Rebuild the user turn with a pointed correction after an integrity miss."""

    problems = []
    if result.missing:
        problems.append(f"you dropped {' '.join(result.missing)}")
    if result.duplicated:
        problems.append(f"you repeated {' '.join(result.duplicated)}")
    if result.unexpected:
        problems.append(f"you invented {' '.join(result.unexpected)}")
    tokens = " ".join(protected.order)
    return (
        "Your previous rewrite broke the protected tokens: "
        + "; ".join(problems)
        + ". Rewrite the passage again. Include each of these tokens exactly once, "
        "and invent none:\n"
        + tokens
        + "\n\nPassage:\n"
        + protected.masked
    )


def _describe(result: VerificationResult | None) -> str:
    if result is None:
        return "no result"
    return (
        f"missing={list(result.missing)} duplicated={list(result.duplicated)} "
        f"invented={list(result.unexpected)}"
    )


def _unique_refs(outcomes: list[_Outcome]) -> list[PromptRef]:
    seen: set[tuple[str, int]] = set()
    refs: list[PromptRef] = []
    for outcome in outcomes:
        for ref in outcome.refs:
            key = (ref.id, ref.version)
            if key not in seen:
                seen.add(key)
                refs.append(ref)
    return refs
