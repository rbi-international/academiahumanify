"""Protection core: mask what must not change, verify it survived, restore it.

The product's one hard problem is rewriting prose without corrupting the
science. The answer is to never trust the model with anything that must stay
exact. Before the model sees a paragraph, every fragile span (a citation, a
p-value, an equation, a DOI, a model name, a unit) is replaced with an opaque
placeholder. The model rewrites the prose around the placeholders. Afterwards we
verify each placeholder came back exactly once, then swap the originals back in.

This module is deterministic and pure. It has no model and no network, so it can
be tested exhaustively and must never regress. Two bugs are locked by named
tests below and explained inline:

  1. Placeholders must contain NO digits. An early version numbered them, and the
     bare-number pattern then masked its own output, corrupting the mapping. The
     fix is a letter-only base-26 encoding.
  2. Tokens that mix letters and digits (model names like GPT-2, Qwen3) must be
     masked whole, ahead of the bare-number rule. Otherwise the "2" in "GPT-2"
     is masked alone and the name fragments into "GPT-" plus a placeholder.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

# Placeholder shape: ⟦P followed by letters, then ⟧. The delimiters are rare in
# academic prose, and the body is letters only so no later digit pattern can
# match inside it. This exact ⟦P...⟧ shape is what the rewrite prompt is told to
# preserve, so do not change it without updating the prompt library.
_PREFIX = "⟦P"  # ⟦P
_SUFFIX = "⟧"  # ⟧
_PLACEHOLDER_RE = re.compile(r"⟦P[A-Z]+⟧")


class IntegrityError(Exception):
    """Raised when masked model output fails placeholder verification.

    A failed integrity check is never downgraded to a warning. The caller
    retries, then fails hard. It is never silently accepted.
    """


def _encode(n: int) -> str:
    """Encode a non-negative index as uppercase letters only (A, B, ... Z, AA...).

    Letters only, on purpose: a placeholder that contained a digit would be
    eaten by the number-masking pass. This is a bijective base-26 scheme so no
    index collides and no placeholder is a substring of another once wrapped in
    the ⟦P...⟧ delimiters.
    """

    letters = ""
    n += 1  # shift to a 1-based bijective base-26 so 0 -> "A", 25 -> "Z", 26 -> "AA"
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


@dataclass(frozen=True)
class ProtectedText:
    """Result of masking: the masked string plus how to undo it.

    `mapping` is placeholder -> original span. `order` preserves the sequence in
    which placeholders were created, which the verifier and tests rely on.
    """

    masked: str
    mapping: dict[str, str]
    order: tuple[str, ...] = field(default_factory=tuple)

    @property
    def placeholders(self) -> tuple[str, ...]:
        return self.order


def _is_mixed_alnum(token: str) -> bool:
    """True only when a token contains both a letter and a digit.

    This is the guard that makes the broad alphanumeric pattern safe. Pure words
    are never masked (they are prose), pure numbers fall through to the dedicated
    number rule, and letter-only placeholders emitted by earlier passes are left
    untouched. Only genuinely mixed tokens (GPT-2, Qwen3, CO2, p53) are masked
    whole so they cannot fragment.
    """

    return any(c.isalpha() for c in token) and any(c.isdigit() for c in token)


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of checking masked model output against the expected placeholders."""

    ok: bool
    missing: tuple[str, ...] = ()
    duplicated: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()

    def raise_if_bad(self) -> None:
        if self.ok:
            return
        parts = []
        if self.missing:
            parts.append(f"dropped {list(self.missing)}")
        if self.duplicated:
            parts.append(f"duplicated {list(self.duplicated)}")
        if self.unexpected:
            parts.append(f"invented {list(self.unexpected)}")
        raise IntegrityError("placeholder integrity failed: " + "; ".join(parts))


# Ordered protection patterns. Order is load-bearing: the most specific and
# longest spans are masked first so that a later, greedier rule (bare numbers)
# cannot carve a hole in the middle of something already recognised. Each entry
# is (name, compiled regex, predicate). A predicate of None means "mask every
# match"; otherwise a match is only masked when the predicate returns True. No
# pattern can ever match an emitted placeholder: every one needs a digit or a
# distinctive delimiter, and the placeholder body is letters only.
_Predicate = Callable[[str], bool]
_PATTERNS: tuple[tuple[str, re.Pattern[str], _Predicate | None], ...] = (
    # LaTeX environments: \begin{...} ... \end{...}, possibly spanning lines.
    ("latex_env", re.compile(r"\\begin\{[^}]*\}.*?\\end\{[^}]*\}", re.DOTALL), None),
    # Display and inline math.
    ("math_display", re.compile(r"\$\$.+?\$\$|\\\[.+?\\\]", re.DOTALL), None),
    ("math_inline", re.compile(r"\$[^$\n]+?\$|\\\(.+?\\\)", re.DOTALL), None),
    # URLs and DOIs, before anything else can nibble their digits.
    ("url", re.compile(r"https?://[^\s)\]]+"), None),
    ("doi", re.compile(r"\bdoi:\s*10\.\d{4,9}/[^\s)\]]+|\b10\.\d{4,9}/[^\s)\]]+"), None),
    # Cross-references: Table 3, Figure 2a, Eq. 4, Section 5.1.
    (
        "ref",
        re.compile(
            r"\b(?:Table|Tab\.|Figure|Fig\.|Eq\.|Equation|Section|Sec\.|Appendix)"
            r"\s*\d+(?:\.\d+)*[a-z]?\b"
        ),
        None,
    ),
    # Numeric citations: [12], [3-5], [1, 2, 7].
    ("cite_num", re.compile(r"\[\s*\d+(?:\s*[-–,]\s*\d+)*\s*\]"), None),
    # Author-year citations: (Smith, 2020), (Smith and Jones, 2019),
    # (Smith et al., 2021), (Smith 2020; Jones 2019).
    (
        "cite_authoryear",
        re.compile(
            r"\([^()]*?\b(?:19|20)\d{2}[a-z]?"
            r"(?:\s*[;,]\s*[^()]*?\b(?:19|20)\d{2}[a-z]?)*\s*\)"
        ),
        None,
    ),
    # p-values kept whole so "p < 0.05" can never soften to "p < 0.5".
    ("p_value", re.compile(r"\bp\s*[<>=≤≥]\s*\.?\d+(?:\.\d+)?", re.IGNORECASE), None),
    # Any token mixing letters and digits, masked whole so model names, gene
    # names, and formulae (GPT-2, Qwen3, p53, CO2, H2O, 5-HT) never fragment.
    # The candidate is broad; the predicate keeps only genuinely mixed tokens,
    # which leaves pure numbers for the number rule and leaves letter-only
    # placeholders untouched. Must run before the bare-number rule.
    (
        "alnum_token",
        re.compile(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\b"),
        _is_mixed_alnum,
    ),
    # Quantities with a spaced unit: "10 mL", "3.5 kg", "20 ms". The no-space
    # form ("10mL") is already caught by alnum_token above.
    (
        "quantity_unit",
        re.compile(
            r"\b\d+(?:\.\d+)?\s?"
            r"(?:%|°[CF]|[npµum]?g|[kmM]?g|[mM]?L|mL|kg|"
            r"[npµm]?s|ms|Hz|[kMG]Hz|[kMG]?B|mm|cm|km|nm)"
            # Not \b here: a trailing word boundary never matches after '%'
            # (both sides non-word), which used to leave a loose percent sign
            # behind. A negative lookahead for an alphanumeric works for units
            # that end in a symbol and units that end in a letter alike.
            r"(?![A-Za-z0-9])"
        ),
        None,
    ),
    # Bare numbers last: integers, decimals, thousands, scientific notation.
    ("number", re.compile(r"\b\d[\d,]*(?:\.\d+)?(?:[eE][-+]?\d+)?\b"), None),
)


def protect(text: str) -> ProtectedText:
    """Mask every fragile span in `text`.

    Returns the masked text and the mapping needed to restore it. Masking is a
    single left-to-right pass per pattern, in the fixed order above, so spans
    never overlap and the round trip is byte-identical.
    """

    mapping: dict[str, str] = {}
    order: list[str] = []
    counter = 0

    working = text
    for _name, pattern, predicate in _PATTERNS:

        def _sub(match: re.Match[str], _predicate: _Predicate | None = predicate) -> str:
            nonlocal counter
            original = match.group(0)
            # A predicate lets a broad pattern decline a match (for example the
            # alphanumeric rule skipping a pure word or pure number).
            if _predicate is not None and not _predicate(original):
                return original
            placeholder = f"{_PREFIX}{_encode(counter)}{_SUFFIX}"
            mapping[placeholder] = original
            order.append(placeholder)
            counter += 1
            return placeholder

        working = pattern.sub(_sub, working)

    return ProtectedText(masked=working, mapping=mapping, order=tuple(order))


def restore(masked: str, mapping: dict[str, str]) -> str:
    """Swap every placeholder back for its original span.

    Uses a single regex pass so a placeholder cannot be partially matched, and
    an unknown placeholder is left untouched rather than raising here (the
    verifier is where integrity is enforced).
    """

    def _sub(match: re.Match[str]) -> str:
        token = match.group(0)
        return mapping.get(token, token)

    return _PLACEHOLDER_RE.sub(_sub, masked)


def verify(masked_output: str, protected: ProtectedText) -> VerificationResult:
    """Check masked model output before restoring.

    Three failure modes, each caught:
      - dropped: an expected placeholder is missing (the model deleted content)
      - duplicated: a placeholder appears more than once (the model copied it)
      - invented: a placeholder that we never created appears (the model made
        one up or mangled an existing one into a different letter string)
    """

    found = _PLACEHOLDER_RE.findall(masked_output)
    counts: dict[str, int] = {}
    for token in found:
        counts[token] = counts.get(token, 0) + 1

    expected = set(protected.mapping)
    missing = tuple(p for p in protected.order if counts.get(p, 0) == 0)
    duplicated = tuple(p for p in protected.order if counts.get(p, 0) > 1)
    unexpected = tuple(sorted(t for t in counts if t not in expected))

    ok = not (missing or duplicated or unexpected)
    return VerificationResult(
        ok=ok, missing=missing, duplicated=duplicated, unexpected=unexpected
    )


def restore_verified(masked_output: str, protected: ProtectedText) -> str:
    """Verify then restore, raising on any integrity failure.

    This is the safe entry point for the rewrite path: it guarantees no
    corrupted output is ever restored and returned.
    """

    verify(masked_output, protected).raise_if_bad()
    return restore(masked_output, protected.mapping)
