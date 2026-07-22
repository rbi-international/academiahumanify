"""M4 claim extractor: pull the assertions out of a paragraph.

Why this exists: the rewrite must not strengthen or weaken what the author
claimed. "The data may suggest a link" and "The data prove a link" say very
different things, and a model asked to "improve flow" will happily slide one
into the other. To catch that later (the verify stage measures drift), we first
need a before-picture: for each sentence, what is being asserted and how firmly.

So this stage reduces a sentence to a claim tuple (subject, relation, object)
plus a hedge strength on a five-point scale, from "may suggest" at the bottom to
"demonstrates" at the top. Comparing the hedge strength of a claim before and
after a rewrite is how drift becomes a number.

Deterministic, regex and rule based, no model. It is a heuristic, not a parser:
it finds the main relational verb, splits the sentence around it, and reads the
firmness off the verb plus any softening modal or strengthening adverb.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

from app.pipeline.stylometry import split_sentences


class HedgeStrength(IntEnum):
    """How firmly a claim is asserted, low to high.

    An IntEnum so drift is just arithmetic: SPECULATIVE < TENTATIVE < ... and a
    rewrite that moves a claim from TENTATIVE to STRONG is a positive delta the
    verify stage can flag.
    """

    SPECULATIVE = 1  # may, might, could; "may suggest"
    TENTATIVE = 2  # suggests, appears, seems, tends
    MODERATE = 3  # shows, indicates, is associated with, causes
    STRONG = 4  # confirms, establishes, reveals; a bare copula assertion
    DEFINITIVE = 5  # demonstrates, proves, guarantees


# Relational cues and the base strength each carries. Longer, more specific
# phrases ("is associated with") are listed alongside their bare verbs; when two
# cues start at the same place the longer match wins, so the phrase beats the
# copula. Order within the list does not matter: the extractor picks the
# earliest cue in the sentence, breaking ties by length.
_RELATIONS: tuple[tuple[re.Pattern[str], HedgeStrength], ...] = (
    (re.compile(r"\bdemonstrates?\b|\bdemonstrated\b", re.I), HedgeStrength.DEFINITIVE),
    (re.compile(r"\bproves?\b|\bproven\b", re.I), HedgeStrength.DEFINITIVE),
    (re.compile(r"\bguarantees?\b|\bguaranteed\b", re.I), HedgeStrength.DEFINITIVE),
    (re.compile(r"\bconfirms?\b|\bconfirmed\b", re.I), HedgeStrength.STRONG),
    (re.compile(r"\bestablishe?s?\b|\bestablished\b", re.I), HedgeStrength.STRONG),
    (re.compile(r"\breveals?\b|\brevealed\b", re.I), HedgeStrength.STRONG),
    (re.compile(r"\bis\s+associated\s+with\b|\bassociated\s+with\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\bis\s+linked\s+to\b|\blinked\s+to\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\bcorrelates?\s+with\b|\bcorrelated\s+with\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\bleads?\s+to\b|\bled\s+to\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\bresults?\s+in\b|\bresulted\s+in\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\bshows?\b|\bshowed\b|\bshown\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\bindicates?\b|\bindicated\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\breports?\b|\breported\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\bfinds?\b|\bfound\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\bcauses?\b|\bcaused\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\bpredicts?\b|\bpredicted\b", re.I), HedgeStrength.MODERATE),
    (re.compile(r"\bsuggests?\b|\bsuggested\b", re.I), HedgeStrength.TENTATIVE),
    (re.compile(r"\bappears?\b|\bappeared\b", re.I), HedgeStrength.TENTATIVE),
    (re.compile(r"\bseems?\b|\bseemed\b", re.I), HedgeStrength.TENTATIVE),
    (re.compile(r"\btends?\b|\btended\b", re.I), HedgeStrength.TENTATIVE),
    (re.compile(r"\bimplies\b|\bimply\b|\bimplied\b", re.I), HedgeStrength.TENTATIVE),
    # Bare copula: an unhedged "X is Y" is a strong assertion. Kept last in
    # spirit (shortest, most generic) but selected only when no richer cue sits
    # earlier in the sentence.
    (re.compile(r"\bis\b|\bare\b|\bwas\b|\bwere\b", re.I), HedgeStrength.STRONG),
)

# Softening modals and adverbs pull a claim down one step; strengthening adverbs
# push it up one. Both are searched only up to and including the relation cue, so
# a "may" buried in the object does not soften the main claim.
_DOWNTONERS = re.compile(
    r"\b(?:may|might|could|possibly|perhaps|potentially|conceivably|arguably"
    r"|presumably|tentatively)\b",
    re.I,
)
_BOOSTERS = re.compile(
    r"\b(?:clearly|conclusively|definitively|unambiguously|strongly|robustly"
    r"|consistently|always|invariably|certainly|undoubtedly)\b",
    re.I,
)


@dataclass(frozen=True)
class Claim:
    """One assertion, reduced so its firmness can be compared before and after.

    `relation` is the verb phrase that was matched, kept verbatim for the audit
    trail. `hedge` is the firmness after any modal or adverb adjustment.
    """

    subject: str
    relation: str
    object: str
    hedge: HedgeStrength
    sentence: str


def _find_relation(sentence: str) -> tuple[re.Match[str], HedgeStrength] | None:
    """Return the main relational cue: the earliest, then the longest.

    Earliest because the first relational verb is almost always the sentence's
    main verb; longest at a tie so a multi-word cue beats the bare copula that
    starts at the same position.
    """

    best: tuple[tuple[int, int], re.Match[str], HedgeStrength] | None = None
    for pattern, level in _RELATIONS:
        for m in pattern.finditer(sentence):
            key = (m.start(), -(m.end() - m.start()))
            if best is None or key < best[0]:
                best = (key, m, level)
    if best is None:
        return None
    return best[1], best[2]


def _adjust(base: HedgeStrength, prefix: str) -> HedgeStrength:
    """Nudge the base strength by one step per softener or booster in `prefix`.

    Clamped to the 1..5 scale. A single sentence rarely carries both, but if it
    does they simply offset.
    """

    level = int(base)
    if _DOWNTONERS.search(prefix):
        level -= 1
    if _BOOSTERS.search(prefix):
        level += 1
    level = max(int(HedgeStrength.SPECULATIVE), min(int(HedgeStrength.DEFINITIVE), level))
    return HedgeStrength(level)


def claim_from_sentence(sentence: str) -> Claim | None:
    """Extract a single claim from one sentence, or None if it asserts nothing.

    A sentence with no relational cue (a heading, an aside, an instruction) is
    not a claim and returns None rather than a hollow tuple.
    """

    sentence = sentence.strip()
    found = _find_relation(sentence)
    if found is None:
        return None
    match, base = found

    subject = sentence[: match.start()].strip()
    obj = sentence[match.end() :].strip().rstrip(".!?").strip()
    if not subject or not obj:
        return None

    hedge = _adjust(base, sentence[: match.end()])
    return Claim(
        subject=subject,
        relation=match.group(0).strip(),
        object=obj,
        hedge=hedge,
        sentence=sentence,
    )


def extract_claims(text: str) -> list[Claim]:
    """Extract every claim from a paragraph or document, in reading order."""

    claims: list[Claim] = []
    for sentence in split_sentences(text):
        claim = claim_from_sentence(sentence)
        if claim is not None:
            claims.append(claim)
    return claims
