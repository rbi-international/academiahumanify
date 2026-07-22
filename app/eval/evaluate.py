"""Deterministic evaluation of one rewrite against its original.

Three questions, in priority order:

1. Fidelity. Did the meaning survive? Protected material must be intact, and a
   claim must not have been strengthened (turning "may suggest" into
   "demonstrates" is the cardinal sin of an academic editor). This is the hard
   gate: fail it and the candidate is never "best", however well it reads.

2. Quality. Does it read human? Fewer machine-writing tells is better: less
   inflated diction, fewer hollow phrases, fewer habitual connectives, real
   sentence-length variation.

3. Voice. When the author gave a writing sample, how close is the rewrite to
   their measured style?

No model, no network. Reused from earlier milestones: the claim extractor (M4)
for drift, the stylometry extractor (M3) for tells and voice.
"""

from __future__ import annotations

import difflib
from dataclasses import asdict, dataclass
from typing import Any

from app.pipeline.claims import Claim, HedgeStrength, extract_claims
from app.pipeline.stylometry import (
    Confidence,
    Tells,
    VoiceProfile,
    extract,
    split_sentences,
)

# A rewrite may drift a little in length without changing meaning. Beyond this
# fraction of the original sentence count we flag it (soft), but merging or
# splitting sentences is normal, so this does not gate.
_SENTENCE_TOLERANCE = 0.5


@dataclass(frozen=True)
class Fidelity:
    """Did the facts and claim strengths survive?"""

    placeholders_ok: bool
    claims_before: int
    claims_after: int
    claim_strengthened: bool  # the dangerous direction: overclaiming
    claim_weakened: bool  # safer, but still drift, so flagged
    sentence_delta: int
    sentence_flag: bool
    passed: bool  # the hard gate: placeholders intact and no claim strengthened


@dataclass(frozen=True)
class Quality:
    """How much the prose reads like a human wrote it."""

    tells_before: int
    tells_after: int
    tells_removed: int
    ai_diction_after: int
    hollow_phrases_after: int
    sentence_length_variance: float
    score: float  # 0..1, higher is better


@dataclass(frozen=True)
class VoiceMatch:
    """Distance from the author's measured voice, when a sample was given."""

    available: bool
    distance: float  # lower is closer
    score: float  # 0..1, higher is better


@dataclass(frozen=True)
class Evaluation:
    """The full scorecard for one rewrite."""

    fidelity: Fidelity
    quality: Quality
    voice: VoiceMatch
    change_ratio: float  # 0 unchanged, 1 completely different
    quality_rank: float  # combined prose + voice, used to rank fidelity-passers

    @property
    def eligible(self) -> bool:
        """Whether this rewrite may be considered 'best'. Fidelity gates it."""
        return self.fidelity.passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "fidelity": asdict(self.fidelity),
            "quality": asdict(self.quality),
            "voice": asdict(self.voice),
            "change_ratio": round(self.change_ratio, 4),
            "quality_rank": round(self.quality_rank, 4),
        }


def _tell_total(tells: Tells) -> int:
    return (
        tells.ai_diction
        + tells.hollow_phrases
        + tells.moreover_family
        + tells.tricolons
        + tells.em_dashes
    )


def _max_hedge(claims: list[Claim]) -> HedgeStrength | None:
    return max((c.hedge for c in claims), default=None)


def _fidelity(original: str, rewritten: str) -> Fidelity:
    placeholders_ok = "⟦P" not in rewritten  # restored text carries no tokens

    before = extract_claims(original)
    after = extract_claims(rewritten)
    om = _max_hedge(before)
    nm = _max_hedge(after)
    strengthened = om is not None and nm is not None and nm > om
    weakened = om is not None and nm is not None and nm < om

    n_before = len(split_sentences(original))
    n_after = len(split_sentences(rewritten))
    delta = n_after - n_before
    flag = n_before > 0 and abs(delta) > _SENTENCE_TOLERANCE * n_before

    passed = placeholders_ok and not strengthened
    return Fidelity(
        placeholders_ok=placeholders_ok,
        claims_before=len(before),
        claims_after=len(after),
        claim_strengthened=strengthened,
        claim_weakened=weakened,
        sentence_delta=delta,
        sentence_flag=flag,
        passed=passed,
    )


def _quality(original: str, rewritten: str) -> Quality:
    before = extract(original)
    after = extract(rewritten)
    tb = before.features.tells
    ta = after.features.tells

    tells_before = _tell_total(tb)
    tells_after = _tell_total(ta)

    # Weight the loudest tells hardest. Em dashes are banned outright, inflated
    # diction and hollow phrases are the strongest AI signals.
    penalty = (
        ta.ai_diction * 2
        + ta.hollow_phrases * 2
        + ta.em_dashes * 3
        + ta.moreover_family
        + ta.tricolons
    )
    # Uniform sentence length is itself a tell.
    if after.sentence_count > 1 and after.features.sentence_length_variance < 4.0:
        penalty += 2

    score = 1.0 / (1.0 + penalty)
    return Quality(
        tells_before=tells_before,
        tells_after=tells_after,
        tells_removed=tells_before - tells_after,
        ai_diction_after=ta.ai_diction,
        hollow_phrases_after=ta.hollow_phrases,
        sentence_length_variance=after.features.sentence_length_variance,
        score=score,
    )


def _voice_match(rewritten: str, voice: VoiceProfile | None) -> VoiceMatch:
    if voice is None or voice.confidence is Confidence.NONE:
        return VoiceMatch(available=False, distance=0.0, score=1.0)

    target = voice.features
    got = extract(rewritten).features

    def rel(a: float, b: float) -> float:
        return abs(a - b) / (abs(b) + 1.0)

    distance = (
        rel(got.sentence_length_mean, target.sentence_length_mean)
        + abs(got.passive_ratio - target.passive_ratio)
        + rel(got.hedging_density, target.hedging_density)
        + rel(got.nominalisation_rate, target.nominalisation_rate)
    )
    return VoiceMatch(available=True, distance=distance, score=1.0 / (1.0 + distance))


def _change_ratio(original: str, rewritten: str) -> float:
    matcher = difflib.SequenceMatcher(a=original.split(), b=rewritten.split())
    return 1.0 - matcher.ratio()


def evaluate(original: str, rewritten: str, voice: VoiceProfile | None = None) -> Evaluation:
    """Score `rewritten` against `original`, optionally against a voice sample."""

    fidelity = _fidelity(original, rewritten)
    quality = _quality(original, rewritten)
    voice_match = _voice_match(rewritten, voice)

    # Among fidelity-passers, rank by how it reads and how close to the author's
    # voice. Voice only counts when a sample was provided.
    if voice_match.available:
        quality_rank = 0.7 * quality.score + 0.3 * voice_match.score
    else:
        quality_rank = quality.score

    return Evaluation(
        fidelity=fidelity,
        quality=quality,
        voice=voice_match,
        change_ratio=_change_ratio(original, rewritten),
        quality_rank=quality_rank,
    )
