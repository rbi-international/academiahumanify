"""M3 stylometry extractor: turn a writing sample into explicit numeric targets.

The plain idea: "write like this person" is a vague instruction a model follows
badly. "Average 22 words per sentence, vary the length a lot, hedge about twice
per hundred words, avoid tricolons" is a concrete one it follows well. So we
measure the author's own past writing and hand the rewrite stage numbers to aim
at, alongside the raw exemplar for feel.

The exact same extractor runs on the draft itself. There it produces the Style
Report: a count of the writer's own machine-writing tells (repeated connectives,
uniform sentence length, tricolons, nominalisation) so the author can see what
to fix. That is an editing signal, not a detector score.

Deterministic, no model, no network. Everything here is a heuristic and is
documented as approximate: sentence splitting and passive detection are rules of
thumb, good enough to steer a prompt, not a parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# A sample shorter than this yields numbers too noisy to steer a rewrite, so we
# still report them but flag the profile as low confidence.
MIN_RELIABLE_WORDS = 80


class Confidence(Enum):
    """How much to trust the extracted numbers."""

    NONE = "none"  # empty sample: nothing measured
    LOW = "low"  # under the reliability threshold: indicative only
    OK = "ok"  # enough text to steer a rewrite


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")
_SENTENCE_TERMINATOR = re.compile(r"(?<=[.!?])\s+")
# Trailing abbreviation or single-letter initial: a period here does not end a
# sentence. Used to re-merge over-eager splits ("et al." "e.g." "J.").
_TRAILING_ABBREV = re.compile(
    r"(?:\b(?:e\.g|i\.e|et al|etc|cf|vs|viz|fig|eq|tab|no|dr|mr|mrs|ms|st|prof"
    r"|approx|ca|sec|ref|al|pp|vol|ed|eds)|\b[A-Za-z])\.$",
    re.IGNORECASE,
)

_CONNECTIVES: tuple[str, ...] = (
    "however", "moreover", "furthermore", "therefore", "thus", "hence",
    "consequently", "additionally", "nevertheless", "nonetheless", "meanwhile",
    "similarly", "conversely", "indeed", "notably", "accordingly",
    "subsequently", "overall", "finally", "firstly", "secondly", "thirdly",
    "besides", "instead", "likewise", "importantly", "specifically", "namely",
    "in addition", "on the other hand", "as a result", "for example",
    "for instance", "in contrast", "in particular",
)

_HEDGES: tuple[str, ...] = (
    "may", "might", "could", "would", "suggest", "suggests", "suggested",
    "appear", "appears", "appeared", "seem", "seems", "seemed", "tend",
    "tends", "tended", "likely", "possibly", "perhaps", "potentially",
    "presumably", "arguably", "apparently", "relatively", "somewhat",
    "generally", "probably",
)

_MOREOVER_FAMILY: tuple[str, ...] = (
    "moreover", "furthermore", "additionally", "in addition", "besides",
)

# Inflated vocabulary that language models reach for far more than human authors.
# Counting it in the draft tells the writer which words to swap for plain ones.
# This is an editing signal, a count of tells, not a detector score.
_AI_DICTION: tuple[str, ...] = (
    "delve", "leverage", "seamless", "seamlessly", "robust", "intricate",
    "pivotal", "crucial", "comprehensive", "realm", "tapestry", "underscore",
    "underscores", "showcase", "showcases", "testament", "landscape",
    "navigate", "foster", "myriad", "nuanced", "meticulous", "meticulously",
    "notably", "furthermore", "moreover",
)

# Hollow throat-clearing phrases that add words without adding content.
_HOLLOW_PHRASES: tuple[str, ...] = (
    "it is important to note", "it is worth noting", "it is worth mentioning",
    "plays a vital role", "plays a key role", "plays a crucial role",
    "a wide range of", "rich tapestry", "in today's world",
    "stands as a testament", "it should be noted",
)

_BE_FORMS = r"(?:am|is|are|was|were|be|been|being)"
_IRREGULAR_PARTICIPLES = (
    "done", "made", "shown", "seen", "found", "given", "taken", "held", "known",
    "built", "brought", "kept", "left", "told", "sent", "put", "set", "run",
    "begun", "drawn", "grown", "written", "chosen", "driven", "proven", "born",
    "worn", "torn", "led", "read", "understood",
)
_PASSIVE_RE = re.compile(
    rf"\b{_BE_FORMS}\b(?:\s+\w+){{0,2}}?\s+"
    rf"(?:\w+ed|{'|'.join(_IRREGULAR_PARTICIPLES)})\b",
    re.IGNORECASE,
)

_NOMINALISATION_SUFFIXES = (
    "tion", "sion", "ment", "ness", "ity", "ance", "ence", "ancy", "ency",
    "ism", "ology",
)

_SUBORDINATORS: frozenset[str] = frozenset(
    {"because", "although", "though", "while", "whereas", "since", "if",
     "unless", "until", "when", "whenever", "where", "that", "which", "who",
     "whom", "whose"}
)

# Three or more comma-separated items closing with "and"/"or": the tricolon.
_TRICOLON_RE = re.compile(
    r"[^,.;:!?()\n]+,\s+[^,.;:!?()\n]+,\s+(?:and|or)\s+[^,.;:!?()\n]+",
    re.IGNORECASE,
)
_EM_DASH_RE = re.compile(r"[—–]")


def _mean(values: list[float] | list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _variance(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return sum((v - m) ** 2 for v in values) / len(values)


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, re-merging splits caused by abbreviations.

    Approximate on purpose. Decimals stay intact because the split only fires on
    a terminator followed by whitespace; "0.05" has no space after its dot.
    """

    flat = re.sub(r"\s+", " ", text.strip())
    if not flat:
        return []
    parts = _SENTENCE_TERMINATOR.split(flat)
    merged: list[str] = []
    for part in parts:
        if merged and _TRAILING_ABBREV.search(merged[-1]):
            merged[-1] = merged[-1] + " " + part
        else:
            merged.append(part)
    return [p.strip() for p in merged if p.strip()]


def _count_phrase(text_lower: str, phrase: str) -> int:
    return len(re.findall(rf"\b{re.escape(phrase)}\b", text_lower))


@dataclass(frozen=True)
class Tells:
    """Machine-writing tells, counted so the author can see what to trim."""

    tricolons: int = 0
    moreover_family: int = 0
    em_dashes: int = 0
    uniform_openings: int = 0
    top_opening_word: str | None = None
    top_opening_count: int = 0
    ai_diction: int = 0  # inflated words models overuse (delve, leverage, ...)
    hollow_phrases: int = 0  # throat-clearing that adds words, not content


@dataclass(frozen=True)
class StyleFeatures:
    """The measured numbers a rewrite prompt can aim at."""

    sentence_length_mean: float = 0.0
    sentence_length_variance: float = 0.0
    sentence_length_min: int = 0
    sentence_length_max: int = 0
    connectives: dict[str, int] = field(default_factory=dict)
    connective_repetition_max: int = 0
    hedging_density: float = 0.0  # hedge words per 100 words
    passive_ratio: float = 0.0  # passive sentences / all sentences
    active_to_passive: float | None = None  # None when there are no passives
    nominalisation_rate: float = 0.0  # nominalisations per 100 words
    clause_depth_mean: float = 0.0  # approx subordinate clauses per sentence
    paragraph_lengths: tuple[int, ...] = ()  # sentences per paragraph
    paragraph_length_mean: float = 0.0
    tells: Tells = field(default_factory=Tells)


@dataclass(frozen=True)
class VoiceProfile:
    """A writing sample reduced to an exemplar plus measured features.

    `exemplar` is the raw text (kept for the prompt's feel signal). `features`
    are the numeric targets. `confidence` says how far to trust them. When used
    on the draft rather than a voice sample, the same object is the Style Report.
    """

    exemplar: str
    word_count: int
    sentence_count: int
    features: StyleFeatures
    confidence: Confidence
    notes: tuple[str, ...] = ()

    @property
    def reliable(self) -> bool:
        return self.confidence is Confidence.OK

    def style_report(self) -> dict[str, object]:
        """The author-facing view: the tells to fix and a couple of key numbers.

        This is the Style Report surface. It is deliberately small and blunt: a
        few counts the writer can act on, not a dashboard.
        """

        t = self.features.tells
        return {
            "tricolons": t.tricolons,
            "moreover_family": t.moreover_family,
            "em_dashes": t.em_dashes,
            "uniform_openings": t.uniform_openings,
            "ai_diction": t.ai_diction,
            "hollow_phrases": t.hollow_phrases,
            "repeated_opening": (
                None if t.top_opening_word is None
                else {"word": t.top_opening_word, "count": t.top_opening_count}
            ),
            "connective_repetition_max": self.features.connective_repetition_max,
            "sentence_length_variance": round(self.features.sentence_length_variance, 2),
            "confidence": self.confidence.value,
        }


def _extract_tells(text: str, sentences: list[str]) -> Tells:
    text_lower = text.lower()

    tricolons = len(_TRICOLON_RE.findall(text))
    moreover = sum(_count_phrase(text_lower, p) for p in _MOREOVER_FAMILY)
    em_dashes = len(_EM_DASH_RE.findall(text))
    ai_diction = sum(_count_phrase(text_lower, w) for w in _AI_DICTION)
    hollow_phrases = sum(text_lower.count(p) for p in _HOLLOW_PHRASES)

    openings: dict[str, int] = {}
    for sentence in sentences:
        words = _WORD_RE.findall(sentence)
        if not words:
            continue
        first = words[0].lower()
        openings[first] = openings.get(first, 0) + 1

    repeated = {w: c for w, c in openings.items() if c >= 2}
    uniform_openings = sum(repeated.values())
    top_word: str | None = None
    top_count = 0
    if repeated:
        top_word, top_count = max(repeated.items(), key=lambda kv: kv[1])

    return Tells(
        tricolons=tricolons,
        moreover_family=moreover,
        em_dashes=em_dashes,
        uniform_openings=uniform_openings,
        top_opening_word=top_word,
        top_opening_count=top_count,
        ai_diction=ai_diction,
        hollow_phrases=hollow_phrases,
    )


def _extract_features(text: str, words: list[str], sentences: list[str]) -> StyleFeatures:
    text_lower = text.lower()
    word_count = len(words)

    lengths = [len(_WORD_RE.findall(s)) for s in sentences]
    lengths = [n for n in lengths if n > 0]

    # Connective inventory and its worst repeat.
    connectives: dict[str, int] = {}
    for conn in _CONNECTIVES:
        n = _count_phrase(text_lower, conn)
        if n:
            connectives[conn] = n
    connective_repetition_max = max(connectives.values(), default=0)

    # Hedging density per 100 words.
    hedge_hits = sum(_count_phrase(text_lower, h) for h in _HEDGES)
    hedging_density = 100.0 * hedge_hits / word_count if word_count else 0.0

    # Passive voice, counted per sentence.
    passive_sentences = sum(1 for s in sentences if _PASSIVE_RE.search(s))
    total_sentences = len(sentences)
    passive_ratio = passive_sentences / total_sentences if total_sentences else 0.0
    active_to_passive = (
        (total_sentences - passive_sentences) / passive_sentences
        if passive_sentences
        else None
    )

    # Nominalisation rate per 100 words.
    nominalisations = sum(
        1
        for w in words
        if len(w) > 5 and w.lower().endswith(_NOMINALISATION_SUFFIXES)
    )
    nominalisation_rate = 100.0 * nominalisations / word_count if word_count else 0.0

    # Approximate clause depth: one main clause plus each subordinator seen.
    depths: list[float] = []
    for s in sentences:
        toks = [w.lower() for w in _WORD_RE.findall(s)]
        depths.append(1.0 + sum(1 for t in toks if t in _SUBORDINATORS))
    clause_depth_mean = _mean(depths)

    # Paragraph length distribution: sentences per paragraph.
    paragraphs = [p for p in re.split(r"\n[ \t]*\n", text) if p.strip()]
    paragraph_lengths = tuple(len(split_sentences(p)) for p in paragraphs)
    paragraph_length_mean = _mean(list(paragraph_lengths))

    return StyleFeatures(
        sentence_length_mean=_mean(lengths),
        sentence_length_variance=_variance(lengths),
        sentence_length_min=min(lengths) if lengths else 0,
        sentence_length_max=max(lengths) if lengths else 0,
        connectives=connectives,
        connective_repetition_max=connective_repetition_max,
        hedging_density=hedging_density,
        passive_ratio=passive_ratio,
        active_to_passive=active_to_passive,
        nominalisation_rate=nominalisation_rate,
        clause_depth_mean=clause_depth_mean,
        paragraph_lengths=paragraph_lengths,
        paragraph_length_mean=paragraph_length_mean,
        tells=_extract_tells(text, sentences),
    )


def extract(text: str) -> VoiceProfile:
    """Measure a piece of writing into a VoiceProfile.

    Runs on a voice sample (to build a target) and on the draft (to build the
    Style Report), the same way each time. Degrades gracefully: an empty sample
    yields a NONE-confidence profile with zeroed features rather than raising,
    and a short sample yields LOW confidence with a note.
    """

    words = _WORD_RE.findall(text)
    word_count = len(words)

    if word_count == 0:
        return VoiceProfile(
            exemplar=text,
            word_count=0,
            sentence_count=0,
            features=StyleFeatures(),
            confidence=Confidence.NONE,
            notes=("empty sample: no features extracted",),
        )

    sentences = split_sentences(text)
    features = _extract_features(text, words, sentences)

    notes: tuple[str, ...]
    if word_count < MIN_RELIABLE_WORDS:
        confidence = Confidence.LOW
        notes = (
            f"sample is {word_count} words, under the {MIN_RELIABLE_WORDS}-word "
            "threshold; targets are indicative only",
        )
    else:
        confidence = Confidence.OK
        notes = ()

    return VoiceProfile(
        exemplar=text,
        word_count=word_count,
        sentence_count=len(sentences),
        features=features,
        confidence=confidence,
        notes=notes,
    )
