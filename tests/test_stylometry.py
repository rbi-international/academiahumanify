"""M3 stylometry extractor tests.

Every done-criterion has a test: the sentence-length stats, the connective and
hedging measures, passive and nominalisation rates, clause depth, the paragraph
distribution, the tell counters, the confidence tiers (full, short, empty), and
the same extractor producing the draft's Style Report.
"""

from __future__ import annotations

import pytest

from app.pipeline.stylometry import (
    Confidence,
    VoiceProfile,
    extract,
    split_sentences,
)

# A voice sample comfortably over the 80-word reliability threshold.
LONG_SAMPLE = (
    "The experiment began with a simple question about scale. We measured the "
    "response of each subject under three conditions, then compared the "
    "aggregate curves. However, the variance surprised us. Some subjects "
    "adapted within minutes, while others never settled. This heterogeneity, "
    "which earlier work had glossed over, turned out to matter more than the "
    "mean. We therefore reanalysed the data by cluster rather than by average, "
    "and a cleaner pattern emerged. The fast adapters shared a trait the slow "
    "ones lacked, and that trait predicted the outcome better than any single "
    "demographic variable we had recorded before the study started."
)


def test_split_sentences_merges_abbreviations() -> None:
    # "Fig." and "et al." must not be read as sentence ends.
    assert split_sentences("See Fig. 3 for details. It works.") == [
        "See Fig. 3 for details.",
        "It works.",
    ]
    assert split_sentences("Smith et al. found gains. We agree.") == [
        "Smith et al. found gains.",
        "We agree.",
    ]


def test_sentence_length_stats() -> None:
    profile = extract("One two three four five. Six seven.")
    f = profile.features
    assert f.sentence_length_mean == pytest.approx(3.5)
    assert f.sentence_length_min == 2
    assert f.sentence_length_max == 5
    assert f.sentence_length_variance == pytest.approx(2.25)


def test_connective_inventory_and_repetition() -> None:
    text = "However, this holds. Moreover, it holds. However, again it holds here."
    f = extract(text).features
    assert f.connectives.get("however") == 2
    assert f.connectives.get("moreover") == 1
    assert f.connective_repetition_max == 2


def test_hedging_density() -> None:
    f = extract("The result may hold and might vary.").features
    # Two hedges (may, might) over seven words -> ~28.6 per 100 words.
    assert f.hedging_density == pytest.approx(200 / 7, rel=1e-3)


def test_passive_ratio_and_active_to_passive() -> None:
    f = extract("The sample was analyzed carefully. We ran the test.").features
    assert f.passive_ratio == pytest.approx(0.5)
    assert f.active_to_passive == pytest.approx(1.0)


def test_active_to_passive_is_none_without_passives() -> None:
    f = extract("We ran the test. We recorded the result.").features
    assert f.passive_ratio == pytest.approx(0.0)
    assert f.active_to_passive is None


def test_nominalisation_rate() -> None:
    f = extract("The utilisation and implementation improved.").features
    # utilisation + implementation = 2 nominalisations over 5 words.
    assert f.nominalisation_rate == pytest.approx(40.0)


def test_clause_depth() -> None:
    f = extract("The model that we built works because it scales.").features
    # One main clause plus two subordinators (that, because).
    assert f.clause_depth_mean == pytest.approx(3.0)


def test_paragraph_length_distribution() -> None:
    text = (
        "First sentence here. Second sentence here. Third one here.\n\n"
        "Fourth sentence now. Fifth sentence now."
    )
    f = extract(text).features
    assert f.paragraph_lengths == (3, 2)
    assert f.paragraph_length_mean == pytest.approx(2.5)


def test_tell_counters() -> None:
    text = (
        "We tested apples, oranges, and pears. Moreover, it works. "
        "Furthermore, it scales. This is key — really. "
        "The cat sat. The dog ran. A bird flew away."
    )
    tells = extract(text).features.tells
    assert tells.tricolons == 1
    assert tells.moreover_family == 2  # moreover + furthermore
    assert tells.em_dashes == 1
    # "The" opens two sentences.
    assert tells.top_opening_word == "the"
    assert tells.top_opening_count == 2
    assert tells.uniform_openings == 2


def test_ai_diction_and_hollow_phrases_are_counted() -> None:
    text = (
        "It is important to note that we delve into a robust and comprehensive "
        "framework. This leverages a seamless pipeline. Moreover, it is worth "
        "noting that the results are nuanced."
    )
    tells = extract(text).features.tells
    # delve, robust, comprehensive, leverages? ("leverages" not in list, "leverage"
    # is) -> delve, robust, comprehensive, seamless, moreover, nuanced = 6.
    assert tells.ai_diction >= 5
    # "it is important to note" + "it is worth noting" = 2 hollow phrases.
    assert tells.hollow_phrases == 2
    report = extract(text).style_report()
    assert report["ai_diction"] == tells.ai_diction
    assert report["hollow_phrases"] == 2


def test_clean_prose_has_no_ai_diction_tells() -> None:
    tells = extract("We measured the decay rate. The value agrees with theory.").features.tells
    assert tells.ai_diction == 0
    assert tells.hollow_phrases == 0


def test_full_sample_populates_features_with_ok_confidence() -> None:
    profile = extract(LONG_SAMPLE)
    assert profile.word_count >= 80
    assert profile.confidence is Confidence.OK
    assert profile.reliable
    assert profile.notes == ()
    f = profile.features
    assert f.sentence_length_mean > 0
    assert profile.sentence_count > 0
    assert "however" in f.connectives  # the sample uses it


def test_short_sample_reports_low_confidence() -> None:
    profile = extract("It may work well.")
    assert profile.confidence is Confidence.LOW
    assert not profile.reliable
    assert profile.notes  # explains the sample is too short
    # Features are still computed, just flagged as indicative.
    assert profile.features.hedging_density > 0


def test_empty_sample_case() -> None:
    for empty in ("", "   \n\n \t "):
        profile = extract(empty)
        assert profile.confidence is Confidence.NONE
        assert profile.word_count == 0
        assert profile.sentence_count == 0
        assert profile.features.sentence_length_mean == 0.0
        assert profile.notes


def test_same_extractor_produces_draft_style_report() -> None:
    """The extractor that profiles a voice sample also profiles the draft to
    produce the Style Report: a small, blunt count of the writer's own tells."""
    draft = (
        "Moreover, the method is fast. Moreover, it is simple, cheap, and clear. "
        "The system works. The results were computed. The results were checked."
    )
    profile: VoiceProfile = extract(draft)
    report = profile.style_report()
    assert report["moreover_family"] == 2
    assert report["tricolons"] == 1
    assert report["repeated_opening"] == {"word": "the", "count": 3}
    assert set(report) >= {
        "tricolons", "moreover_family", "em_dashes", "uniform_openings",
        "repeated_opening", "connective_repetition_max",
        "sentence_length_variance", "confidence",
    }
