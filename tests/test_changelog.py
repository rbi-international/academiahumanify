"""M9 changelog tests: sentence alignment and the reason for each change."""

from __future__ import annotations

from app.pipeline.base import Document, Segment
from app.pipeline.changelog import build_changelog, changelog_for_documents


def _reasons(original: str, rewritten: str) -> list[str]:
    return [e.reason for e in build_changelog(original, rewritten).entries]


def test_unchanged_sentence() -> None:
    text = "The method works on the data."
    log = build_changelog(text, text)
    assert [e.reason for e in log.entries] == ["unchanged"]
    assert log.changed() == ()


def test_reworded_sentence() -> None:
    reasons = _reasons(
        "The model attained the highest score across the board.",
        "The model reached the top score everywhere in the board.",
    )
    assert reasons == ["reworded"]


def test_merge_is_detected() -> None:
    original = "The proposed method is fast. The proposed method is accurate."
    rewritten = "The proposed method is fast and accurate."
    entries = build_changelog(original, rewritten).entries
    assert len(entries) == 1
    assert entries[0].reason == "merged"
    assert entries[0].original_indices == (0, 1)
    assert entries[0].rewritten_indices == (0,)


def test_split_is_detected() -> None:
    original = "The proposed method is fast and accurate."
    rewritten = "The proposed method is fast. The proposed method is accurate."
    entries = build_changelog(original, rewritten).entries
    assert len(entries) == 1
    assert entries[0].reason == "split"
    assert entries[0].rewritten_indices == (0, 1)


def test_connective_replaced() -> None:
    reasons = _reasons(
        "Moreover, the method works well on the benchmark.",
        "The method works well on the benchmark.",
    )
    assert reasons == ["connective replaced"]


def test_deverbalised() -> None:
    reasons = _reasons(
        "The utilisation of the algorithm was performed by the research team.",
        "The research team used the algorithm.",
    )
    assert reasons == ["deverbalised"]


def test_redundancy_removed() -> None:
    reasons = _reasons(
        "It should be noted that the results, which are quite something, were positive overall.",
        "The results were positive.",
    )
    assert reasons == ["redundancy removed"]


def test_reordered() -> None:
    original = "The sky is blue. The grass is green. The sun is bright."
    rewritten = "The sun is bright. The sky is blue. The grass is green."
    reasons = _reasons(original, rewritten)
    assert "reordered" in reasons


def test_added_sentence() -> None:
    original = "The method works."
    rewritten = "The method works. We also tested it on new data thoroughly."
    entries = build_changelog(original, rewritten).entries
    reasons = [e.reason for e in entries]
    assert "added" in reasons
    added = next(e for e in entries if e.reason == "added")
    assert added.original_indices == ()


def test_deleted_sentence() -> None:
    original = "The method works. This sentence is redundant filler entirely, nothing more."
    rewritten = "The method works."
    reasons = _reasons(original, rewritten)
    assert "deleted" in reasons


def test_summary_and_to_dict() -> None:
    log = build_changelog(
        "Moreover, the method works. The method is slow.",
        "The method works. The method is slow.",
    )
    summary = log.summary()
    assert summary.get("unchanged") == 1
    assert summary.get("connective replaced") == 1
    d = log.to_dict()
    assert "summary" in d and "entries" in d
    assert d["entries"][0]["reason"] in {"connective replaced", "unchanged"}


def test_changelog_for_documents() -> None:
    original = Document(
        text="",
        segments=(
            Segment(index=0, text="# Results", heading=True, frozen=True, kind="heading"),
            Segment(index=1, text="Moreover, the method works well here.", kind="paragraph"),
        ),
    )
    rewritten = Document(
        text="",
        segments=(
            Segment(index=0, text="# Results", heading=True, frozen=True, kind="heading"),
            Segment(index=1, text="The method works well here.", kind="paragraph"),
        ),
    )
    log = changelog_for_documents(original, rewritten)
    reasons = {e.reason for e in log.entries}
    # The frozen heading is unchanged; the paragraph lost its connective.
    assert "unchanged" in reasons
    assert "connective replaced" in reasons
