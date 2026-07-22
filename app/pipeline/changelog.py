"""M9 changelog stage: say what changed, sentence by sentence, and why.

The product promises the author an honest account of every edit, not a black
box. So after the rewrite we align the original sentences to the rewritten ones
and label each change with a plain reason: two sentences merged, one split, a
clause reordered, a nominalisation turned back into a verb, a hollow connective
dropped, redundancy trimmed. The same record drives both the side-by-side diff
in the UI and the exported change list.

Alignment is fuzzy on purpose: a rewritten sentence rarely matches its source
word for word, so we match on similarity, then read the shape of the change
(many-to-one is a merge, one-to-many a split) and the nature of the wording.

Deterministic, no model. Similarity is difflib; sentence splitting is M3's.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from app.pipeline.base import Document, StageReport
from app.pipeline.stylometry import split_sentences

# Below this similarity two sentences are treated as unrelated (a delete plus an
# add), not as one edited into the other.
_MATCH_THRESHOLD = 0.3
# When only the leading connective differs, the rest must still line up this well.
_CONNECTIVE_REMAINDER = 0.8
# A rewrite this much shorter counts as trimming redundancy.
_REDUNDANCY_RATIO = 0.75

_CONNECTIVES = frozenset(
    {"moreover", "furthermore", "however", "therefore", "thus", "additionally",
     "consequently", "hence", "nevertheless", "nonetheless", "indeed", "notably",
     "accordingly", "meanwhile", "similarly", "conversely", "besides", "importantly"}
)
_NOMINAL_SUFFIXES = ("tion", "sion", "ment", "ness", "ity", "ance", "ence", "ism")


@dataclass(frozen=True)
class ChangeEntry:
    """One aligned change between the original and the rewrite."""

    reason: str
    original_indices: tuple[int, ...]
    rewritten_indices: tuple[int, ...]
    original_text: str
    rewritten_text: str


@dataclass(frozen=True)
class Changelog:
    """The full set of changes, in original reading order."""

    entries: tuple[ChangeEntry, ...]

    def changed(self) -> tuple[ChangeEntry, ...]:
        return tuple(e for e in self.entries if e.reason != "unchanged")

    def summary(self) -> dict[str, int]:
        return dict(Counter(e.reason for e in self.entries))

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary(), "entries": [asdict(e) for e in self.entries]}

    def to_stage_report(self) -> StageReport:
        return StageReport(
            stage="changelog",
            ok=True,
            notes={"entries": len(self.entries), "changed": len(self.changed()),
                   "summary": self.summary()},
        )


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _leading_connective(sentence: str) -> tuple[str | None, str]:
    match = re.match(r"^\s*([A-Za-z]+)\b[,\s]+(.*)$", sentence)
    if match and match.group(1).lower() in _CONNECTIVES:
        return match.group(1).lower(), match.group(2)
    return None, sentence


def _nominalisations(sentence: str) -> int:
    words = re.findall(r"[A-Za-z]+", sentence.lower())
    return sum(1 for w in words if len(w) > 5 and w.endswith(_NOMINAL_SUFFIXES))


def _wording_reason(original: str, rewritten: str) -> str:
    conn_o, rest_o = _leading_connective(original)
    conn_r, rest_r = _leading_connective(rewritten)
    if conn_o != conn_r and _sim(rest_o, rest_r) >= _CONNECTIVE_REMAINDER:
        return "connective replaced"
    if _nominalisations(original) > _nominalisations(rewritten):
        return "deverbalised"
    if len(rewritten.split()) <= _REDUNDANCY_RATIO * max(1, len(original.split())):
        return "redundancy removed"
    return "reworded"


def _entry(
    reason: str,
    original_indices: list[int],
    rewritten_indices: list[int],
    o: list[str],
    r: list[str],
) -> ChangeEntry:
    return ChangeEntry(
        reason=reason,
        original_indices=tuple(original_indices),
        rewritten_indices=tuple(rewritten_indices),
        original_text=" ".join(o[i] for i in original_indices),
        rewritten_text=" ".join(r[j] for j in rewritten_indices),
    )


def _best_matches(source: list[str], target: list[str]) -> list[int | None]:
    """For each source sentence, the index of its most similar target, or None."""
    result: list[int | None] = []
    for s in source:
        best_j, best_score = -1, 0.0
        for j, t in enumerate(target):
            score = _sim(s, t)
            if score > best_score:
                best_score, best_j = score, j
        result.append(best_j if best_score >= _MATCH_THRESHOLD else None)
    return result


def build_changelog(original: str, rewritten: str) -> Changelog:
    """Align `original` to `rewritten` at the sentence level and label changes."""

    o = split_sentences(original)
    r = split_sentences(rewritten)

    best_r_for_o = _best_matches(o, r)
    best_o_for_r = _best_matches(r, o)

    consumed_o: set[int] = set()
    consumed_r: set[int] = set()
    entries: list[tuple[int, ChangeEntry]] = []  # (sort key, entry)

    # Merges: several originals collapse into one rewritten sentence.
    for j in range(len(r)):
        origins = [i for i in range(len(o)) if best_r_for_o[i] == j and i not in consumed_o]
        if len(origins) >= 2:
            entries.append((min(origins), _entry("merged", origins, [j], o, r)))
            consumed_o.update(origins)
            consumed_r.add(j)

    # Splits: one original fans out into several rewritten sentences.
    for i in range(len(o)):
        if i in consumed_o:
            continue
        dests = [j for j in range(len(r)) if best_o_for_r[j] == i and j not in consumed_r]
        if len(dests) >= 2:
            entries.append((i, _entry("split", [i], dests, o, r)))
            consumed_o.add(i)
            consumed_r.update(dests)

    # One-to-one pairs. Detect reordering across the surviving pairs first.
    pairs: list[tuple[int, int]] = []
    for i in range(len(o)):
        candidate = best_r_for_o[i]
        if i not in consumed_o and candidate is not None and candidate not in consumed_r:
            pairs.append((i, candidate))

    reordered: set[int] = set()
    max_j = -1
    for i, j in sorted(pairs, key=lambda p: p[0]):
        if j < max_j:
            reordered.add(i)
        else:
            max_j = j

    for i, j in pairs:
        if i in reordered:
            reason = "reordered"
        elif o[i] == r[j]:
            reason = "unchanged"
        else:
            reason = _wording_reason(o[i], r[j])
        entries.append((i, _entry(reason, [i], [j], o, r)))
        consumed_o.add(i)
        consumed_r.add(j)

    # Whatever is left: an original with no home was deleted, a rewritten with no
    # source was added.
    for i in range(len(o)):
        if i not in consumed_o:
            entries.append((i, _entry("deleted", [i], [], o, r)))
    for j in range(len(r)):
        if j not in consumed_r:
            # Sort added sentences by where they land, biased after their neighbours.
            entries.append((len(o) + j, _entry("added", [], [j], o, r)))

    entries.sort(key=lambda pair: pair[0])
    return Changelog(entries=tuple(entry for _, entry in entries))


def _joined(doc: Document) -> str:
    if doc.segments:
        return "\n\n".join(segment.text for segment in doc.segments)
    return doc.text


def changelog_for_documents(original: Document, rewritten: Document) -> Changelog:
    """Build a changelog from two documents.

    Compared segment by segment so a frozen heading or table stays its own entry
    rather than bleeding into the prose around it. Falls back to whole-text
    alignment when the segment structures do not line up.
    """

    o_segs = original.segments
    r_segs = rewritten.segments
    if not (o_segs and r_segs and len(o_segs) == len(r_segs)):
        return build_changelog(_joined(original), _joined(rewritten))

    entries: list[ChangeEntry] = []
    for o, r in zip(o_segs, r_segs, strict=True):
        if o.frozen or r.frozen:
            reason = "unchanged" if o.text == r.text else "reworded"
            entries.append(ChangeEntry(reason, (o.index,), (r.index,), o.text, r.text))
        else:
            entries.extend(build_changelog(o.text, r.text).entries)
    return Changelog(entries=tuple(entries))
