"""M1 protection core tests.

The protection layer is the moat: deterministic, exhaustively tested, and never
allowed to regress. Two of these are named regression tests for real bugs that
already bit us (digits in placeholders, and model names fragmenting).
"""

from __future__ import annotations

from app.core.protection import (
    IntegrityError,
    protect,
    restore,
    restore_verified,
    verify,
)


def _round_trip(text: str) -> str:
    p = protect(text)
    return restore(p.masked, p.mapping)


def test_masks_numeric_citations() -> None:
    text = "The effect holds [12] and replicates [3-5, 9]."
    p = protect(text)
    assert "[12]" not in p.masked
    assert "[3-5, 9]" not in p.masked
    assert _round_trip(text) == text


def test_masks_author_year_citations() -> None:
    text = "As shown (Smith et al., 2021) and later (Jones and Lee, 2019)."
    p = protect(text)
    assert "2021" not in p.masked
    assert "Jones and Lee, 2019" not in p.masked
    assert _round_trip(text) == text


def test_masks_p_values() -> None:
    text = "The difference was significant (p < 0.05) but not for the control."
    p = protect(text)
    # The whole p-value is one span, so a rewrite cannot soften 0.05 to 0.5.
    assert "0.05" not in p.masked
    assert "p < 0.05" not in p.masked
    assert _round_trip(text) == text


def test_masks_inline_and_display_equations() -> None:
    text = r"We define $x = 5$ inline and $$E = mc^2$$ as a block."
    p = protect(text)
    assert "$x = 5$" not in p.masked
    assert "E = mc^2" not in p.masked
    assert _round_trip(text) == text


def test_masks_latex_environments() -> None:
    text = "Before.\n\\begin{equation}\na^2 + b^2 = c^2\n\\end{equation}\nAfter."
    p = protect(text)
    assert "\\begin{equation}" not in p.masked
    assert "a^2 + b^2 = c^2" not in p.masked
    assert p.masked.startswith("Before.")
    assert p.masked.endswith("After.")
    assert _round_trip(text) == text


def test_masks_table_and_figure_refs() -> None:
    text = "See Table 3 and Figure 2a; details in Section 5.1 and Eq. 4."
    p = protect(text)
    for ref in ("Table 3", "Figure 2a", "Section 5.1", "Eq. 4"):
        assert ref not in p.masked
    assert _round_trip(text) == text


def test_masks_dois() -> None:
    text = "Available at doi:10.1000/xyz123 and also 10.1145/3292500.3330701 online."
    p = protect(text)
    assert "10.1000/xyz123" not in p.masked
    assert "10.1145/3292500.3330701" not in p.masked
    assert _round_trip(text) == text


def test_masks_urls() -> None:
    text = "The dataset lives at https://example.org/data?id=42 for download."
    p = protect(text)
    assert "https://example.org/data?id=42" not in p.masked
    assert _round_trip(text) == text


def test_masks_quantities_and_units() -> None:
    text = "We dosed 10 mL and recorded a 95% response within 20 ms of onset."
    p = protect(text)
    # The whole quantity, unit included, is one masked span.
    assert "10 mL" in p.mapping.values()
    assert "95%" in p.mapping.values()
    assert "20 ms" in p.mapping.values()
    # No unit fragment is left loose in the prose.
    assert "%" not in p.masked
    assert _round_trip(text) == text


def test_percent_unit_is_masked_with_its_number() -> None:
    """Regression: quantity_unit ended in \\b, which never matches after '%'
    (both sides non-word), so "12.4%" masked only "12.4" and left a loose '%'
    the model could later move or drop."""
    text = "accuracy rose by 12.4% overall"
    p = protect(text)
    assert "12.4%" in p.mapping.values()
    assert "%" not in p.masked
    assert _round_trip(text) == text


def test_model_names_not_fragmented() -> None:
    """Regression: GPT-2 once split at the digit, leaving a dangling 'GPT-'.

    Mixed letter-and-digit tokens must be masked whole, ahead of the bare-number
    rule, so the name survives as one unit.
    """
    text = "We compared GPT-2, Qwen3, and BERT on the CO2 corpus with the p53 marker."
    p = protect(text)
    for token in ("GPT-2", "Qwen3", "CO2", "p53"):
        assert token not in p.masked
        assert token in p.mapping.values()
    # No stray fragment left behind.
    assert "GPT-" not in p.masked
    # A pure word with no digit stays as prose, not masked.
    assert "BERT" in p.masked
    assert _round_trip(text) == text


def test_placeholders_contain_no_digits() -> None:
    """Regression: numbered placeholders were eaten by the number-masking pass.

    Every placeholder body must be letters only so masking never consumes its
    own output.
    """
    text = "Values 1, 2, 3 across [4] runs at p < 0.01 with GPT-4 and 5 mL doses."
    p = protect(text)
    assert p.mapping, "expected at least one placeholder"
    for placeholder in p.mapping:
        body = placeholder.removeprefix("⟦P").removesuffix("⟧")
        assert body.isalpha(), f"placeholder {placeholder!r} contains a non-letter"
    assert _round_trip(text) == text


def test_round_trip_is_byte_identical() -> None:
    text = (
        "In prior work (Smith et al., 2020) the GPT-2 model reached 92% accuracy "
        "[3-5] with p < 0.001; see Table 2 and $\\alpha = 0.5$ at doi:10.1/abc.\n\n"
        "A second paragraph dosed 10 mL and cited https://example.org/x for CO2."
    )
    assert _round_trip(text) == text


def test_verify_catches_dropped_invented_and_duplicated() -> None:
    text = "Two spans: [1] and (Doe, 2020)."
    p = protect(text)
    tokens = list(p.mapping)
    assert len(tokens) == 2

    # Clean output verifies and restores.
    assert verify(p.masked, p).ok
    assert restore_verified(p.masked, p) == text

    # Dropped: remove one placeholder.
    dropped = p.masked.replace(tokens[0], "", 1)
    result = verify(dropped, p)
    assert not result.ok and tokens[0] in result.missing

    # Duplicated: repeat one placeholder.
    duped = p.masked.replace(tokens[1], tokens[1] + " " + tokens[1], 1)
    result = verify(duped, p)
    assert not result.ok and tokens[1] in result.duplicated

    # Invented: inject a placeholder we never created.
    invented = p.masked + " ⟦PZZZZ⟧"
    result = verify(invented, p)
    assert not result.ok and "⟦PZZZZ⟧" in result.unexpected

    # Any failure raises through the safe entry point.
    try:
        restore_verified(dropped, p)
    except IntegrityError:
        pass
    else:  # pragma: no cover - the assert above guarantees we do not reach here
        raise AssertionError("expected IntegrityError on dropped placeholder")
