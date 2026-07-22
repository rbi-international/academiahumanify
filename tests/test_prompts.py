"""M6 prompt library tests.

Covers loading by id and version, checksums, the mandatory placeholder rule in
the rewrite prompt, the intensity and style variants, the per-field few-shot
pairs, composition, and the house-style ban on em dashes and filler words.
"""

from __future__ import annotations

import hashlib

import pytest

from app.pipeline.base import Intensity
from app.prompts import (
    Discipline,
    PromptRegistry,
    StyleVariant,
    compose_rewrite_system,
    default_registry,
)

_BANNED_WORDS = ("delve", "leverage", "seamless", "robust solution")


def test_registry_loads_expected_ids() -> None:
    reg = default_registry()
    ids = set(reg.ids())
    assert "system/rewrite" in ids
    assert {
        "system/intensity/conservative",
        "system/intensity/balanced",
        "system/intensity/enhanced",
    } <= ids
    assert {
        "system/style/formal_conservative",
        "system/style/modern_interdisciplinary",
    } <= ids
    assert {
        "fewshot/cs",
        "fewshot/biology",
        "fewshot/physics",
        "fewshot/social_science",
    } <= ids


def test_get_defaults_to_latest_version() -> None:
    reg = default_registry()
    prompt = reg.get("system/rewrite")
    assert prompt.version == 1  # only v1 exists so far
    assert reg.get("system/rewrite", 1) is prompt


def test_get_unknown_id_or_version_raises() -> None:
    reg = default_registry()
    with pytest.raises(KeyError):
        reg.get("system/does-not-exist")
    with pytest.raises(KeyError):
        reg.get("system/rewrite", 99)


def test_checksum_matches_file_text() -> None:
    reg = default_registry()
    prompt = reg.get("system/rewrite")
    expected = hashlib.sha256(prompt.text.encode("utf-8")).hexdigest()
    assert prompt.checksum == expected
    assert prompt.short_checksum == expected[:12]
    # Different prompts have different checksums.
    other = reg.get("system/intensity/balanced")
    assert other.checksum != prompt.checksum


def test_rewrite_prompt_states_the_placeholder_rule() -> None:
    text = default_registry().get("system/rewrite").text
    assert "⟦P" in text
    assert "unchanged" in text
    # The three failure modes it must forbid.
    for phrase in ("never invent", "never drop", "never repeat"):
        assert phrase in text


def test_every_intensity_variant_exists() -> None:
    reg = default_registry()
    for intensity in Intensity:
        prompt = reg.get(f"system/intensity/{intensity.value}")
        assert prompt.text.strip()


def test_every_style_variant_exists() -> None:
    reg = default_registry()
    for style in StyleVariant:
        prompt = reg.get(f"system/style/{style.value}")
        assert prompt.text.strip()


def test_fewshot_pairs_exist_for_every_field() -> None:
    reg = default_registry()
    for field in Discipline:
        prompt = reg.get(f"fewshot/{field.value}")
        assert "BEFORE:" in prompt.text
        assert "AFTER:" in prompt.text


def test_fewshot_examples_preserve_placeholder_counts() -> None:
    # An example that dropped or added a token would teach the model to do the
    # same, so BEFORE and AFTER must carry the identical set of tokens.
    reg = default_registry()
    for field in Discipline:
        text = reg.get(f"fewshot/{field.value}").text
        before, after = text.split("AFTER:")
        before = before.split("BEFORE:")[1]
        tokens_before = sorted(_tokens(before))
        tokens_after = sorted(_tokens(after))
        assert tokens_before == tokens_after, field


def test_compose_fills_slots_and_records_refs() -> None:
    rendered = compose_rewrite_system(
        Intensity.BALANCED, StyleVariant.MODERN_INTERDISCIPLINARY, Discipline.BIOLOGY
    )
    # No unfilled template slots survive.
    assert "{{" not in rendered.text and "}}" not in rendered.text
    # The chosen fragments are actually spliced in.
    assert "Intensity: balanced." in rendered.text
    assert "Style: modern and interdisciplinary." in rendered.text
    assert "Field: biology." in rendered.text
    # One ref per fragment, each carrying a checksum.
    ref_ids = [r.id for r in rendered.refs]
    assert ref_ids == [
        "system/rewrite",
        "system/intensity/balanced",
        "system/style/modern_interdisciplinary",
        "fewshot/biology",
    ]
    assert all(len(r.checksum) == 64 for r in rendered.refs)


def test_compose_without_discipline_omits_example() -> None:
    rendered = compose_rewrite_system(
        Intensity.CONSERVATIVE, StyleVariant.FORMAL_CONSERVATIVE
    )
    assert "Example of the transformation" not in rendered.text
    assert len(rendered.refs) == 3
    assert "Intensity: conservative." in rendered.text


def test_no_prompt_uses_em_dashes_or_banned_words() -> None:
    for prompt in default_registry().all():
        assert "—" not in prompt.text, f"em dash in {prompt.id}"
        lowered = prompt.text.lower()
        for word in _BANNED_WORDS:
            assert word not in lowered, f"{word!r} in {prompt.id}"


def test_registry_reports_missing_root() -> None:
    with pytest.raises(FileNotFoundError):
        PromptRegistry("this/path/does/not/exist")


def _tokens(text: str) -> list[str]:
    import re

    return re.findall(r"⟦P[A-Z]+⟧", text)
