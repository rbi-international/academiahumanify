"""M4 claim extractor tests.

Covers the claim tuple, the five-point hedge scale, softening and boosting,
multi-word relations, multiple claims per paragraph, non-claim sentences, and
determinism.
"""

from __future__ import annotations

from app.pipeline.claims import (
    Claim,
    HedgeStrength,
    claim_from_sentence,
    extract_claims,
)


def test_hedge_scale_is_ordered() -> None:
    assert (
        HedgeStrength.SPECULATIVE
        < HedgeStrength.TENTATIVE
        < HedgeStrength.MODERATE
        < HedgeStrength.STRONG
        < HedgeStrength.DEFINITIVE
    )
    assert [s.value for s in HedgeStrength] == [1, 2, 3, 4, 5]


def test_extracts_subject_relation_object() -> None:
    claim = claim_from_sentence("The results show a clear effect.")
    assert claim is not None
    assert claim.subject == "The results"
    assert claim.relation.lower() == "show"
    assert claim.object == "a clear effect"


def test_may_suggest_is_speculative() -> None:
    # "suggest" alone is TENTATIVE; the modal "may" softens it one step.
    claim = claim_from_sentence("The treatment may suggest a benefit.")
    assert claim is not None
    assert claim.hedge is HedgeStrength.SPECULATIVE


def test_suggests_is_tentative() -> None:
    claim = claim_from_sentence("The data suggest an association.")
    assert claim is not None
    assert claim.hedge is HedgeStrength.TENTATIVE


def test_shows_is_moderate() -> None:
    claim = claim_from_sentence("The analysis shows an increase.")
    assert claim is not None
    assert claim.hedge is HedgeStrength.MODERATE


def test_demonstrates_is_definitive() -> None:
    claim = claim_from_sentence("The experiment demonstrates causation.")
    assert claim is not None
    assert claim.hedge is HedgeStrength.DEFINITIVE


def test_booster_raises_strength() -> None:
    # "confirms" is STRONG; "clearly" pushes it to DEFINITIVE.
    plain = claim_from_sentence("The study confirms the effect.")
    boosted = claim_from_sentence("The study clearly confirms the effect.")
    assert plain is not None and boosted is not None
    assert plain.hedge is HedgeStrength.STRONG
    assert boosted.hedge is HedgeStrength.DEFINITIVE


def test_multiword_relation_associated_with() -> None:
    claim = claim_from_sentence("Smoking is associated with cancer.")
    assert claim is not None
    assert claim.subject == "Smoking"
    assert claim.relation.lower() == "is associated with"
    assert claim.object == "cancer"
    assert claim.hedge is HedgeStrength.MODERATE


def test_downtoner_in_object_does_not_soften_main_claim() -> None:
    # The "may" sits after the relation, in the object, so it must not lower the
    # firmness of "demonstrates".
    claim = claim_from_sentence("The trial demonstrates that treatment may help.")
    assert claim is not None
    assert claim.hedge is HedgeStrength.DEFINITIVE


def test_multiple_claims_in_paragraph() -> None:
    text = (
        "The data suggest an association. "
        "A follow-up experiment demonstrates causation. "
        "This proves the mechanism."
    )
    claims = extract_claims(text)
    assert [c.hedge for c in claims] == [
        HedgeStrength.TENTATIVE,
        HedgeStrength.DEFINITIVE,
        HedgeStrength.DEFINITIVE,
    ]


def test_sentence_without_a_claim_is_skipped() -> None:
    assert claim_from_sentence("See the appendix for further details.") is None
    assert extract_claims("Consider the following two groups of participants.") == []


def test_extraction_is_deterministic() -> None:
    text = "The model shows gains. The ablation may suggest a cause."
    first = extract_claims(text)
    second = extract_claims(text)
    assert first == second
    assert all(isinstance(c, Claim) for c in first)
