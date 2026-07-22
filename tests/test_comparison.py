"""Comparison service tests: ranking, the fidelity gate, and failure isolation.

Uses small fake providers that transform the masked prompt in fixed ways, so the
service runs the real pipeline (segment, rewrite, restore, evaluate) end to end
with no model and no network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.llm.base import TokenUsage
from app.llm.catalog import ModelCatalog
from app.pipeline.base import Intensity, RunContext
from app.services import compare, compare_with_providers

SAMPLE = "Moreover, the utilisation of the method may suggest a benefit on dataset [17]."


class _Provider:
    """A fake model: applies a fixed edit to the masked prompt it is given."""

    name = "fake"

    def __init__(self, transform: Any) -> None:
        self._transform = transform
        self.usage = TokenUsage()

    def complete(self, prompt: str, system: str | None = None, **opts: Any) -> str:
        out = self._transform(prompt)
        self.usage.add(len(prompt.split()), len(out.split()))
        return out


def _echo(prompt: str) -> str:
    return prompt


def _clean(prompt: str) -> str:
    # Drop the machine tells, keep the hedge and the ⟦P...⟧ token.
    return prompt.replace(
        "Moreover, the utilisation of the method may suggest a benefit",
        "The method may suggest a benefit",
    )


def _strengthen(prompt: str) -> str:
    # Overclaim: turn the hedge into a firm assertion (keeps the token intact).
    return prompt.replace("may suggest", "demonstrates")


def _broken(prompt: str) -> str:
    return "this reply dropped every protected token"


def test_ranks_eligible_by_quality_and_isolates_failures() -> None:
    providers = {
        "clean": _Provider(_clean),
        "echo": _Provider(_echo),
        "strengthen": _Provider(_strengthen),
        "broken": _Provider(_broken),
    }
    comp = compare_with_providers(SAMPLE, providers, RunContext(intensity=Intensity.BALANCED))

    order = [c.model_id for c in comp.candidates]
    # Clean (eligible, best prose) first, then echo (eligible, weaker), then the
    # strengthener (ran but failed the fidelity gate), then the broken one.
    assert order == ["clean", "echo", "strengthen", "broken"]

    by_id = {c.model_id: c for c in comp.candidates}
    assert by_id["clean"].eligible and by_id["echo"].eligible
    assert by_id["strengthen"].ok and not by_id["strengthen"].eligible
    assert by_id["strengthen"].evaluation.fidelity.claim_strengthened
    assert not by_id["broken"].ok and by_id["broken"].error is not None

    assert comp.best().model_id == "clean"


def test_best_is_none_when_nothing_passes_the_gate() -> None:
    providers = {"strengthen": _Provider(_strengthen), "broken": _Provider(_broken)}
    comp = compare_with_providers(SAMPLE, providers, RunContext())
    assert comp.best() is None


def test_clean_beats_echo_on_quality() -> None:
    providers = {"echo": _Provider(_echo), "clean": _Provider(_clean)}
    comp = compare_with_providers(SAMPLE, providers, RunContext())
    by_id = {c.model_id: c for c in comp.candidates}
    assert by_id["clean"].evaluation.quality.score > by_id["echo"].evaluation.quality.score
    # The clean rewrite removed the Moreover tell; the echo kept it.
    assert by_id["clean"].evaluation.quality.ai_diction_after == 0
    assert by_id["echo"].evaluation.quality.ai_diction_after >= 1


def test_facts_are_restored_in_the_rewritten_text() -> None:
    providers = {"clean": _Provider(_clean)}
    comp = compare_with_providers(SAMPLE, providers, RunContext())
    assert "[17]" in comp.candidates[0].rewritten_text  # citation came back exactly


def test_comparison_serialises_to_dict() -> None:
    comp = compare_with_providers(SAMPLE, {"clean": _Provider(_clean)}, RunContext())
    d = comp.to_dict()
    assert d["best"] == "clean"
    assert d["candidates"][0]["evaluation"]["eligible"] is True
    assert d["original_text"]


_TOML = """
[[model]]
id = "stub-echo"
display_name = "Stub"
provider = "stub"
tier = "local"
enabled = true

[[model]]
id = "hosted-x"
display_name = "Hosted X"
provider = "openai_compat"
model = "x"
base_url = "https://api.example.com/v1"
api_key_env = "MISSING_KEY_FOR_TEST"
tier = "hosted"
enabled = true
"""


def test_compare_via_catalog_flags_unavailable_models(tmp_path: Path) -> None:
    path = tmp_path / "models.toml"
    path.write_text(_TOML, encoding="utf-8")
    catalog = ModelCatalog.from_toml(path)

    comp = compare(
        SAMPLE, ["stub-echo", "hosted-x"], RunContext(), catalog=catalog, max_workers=2
    )
    by_id = {c.model_id: c for c in comp.candidates}
    # The stub runs (echo), the keyless hosted model is reported unavailable.
    assert by_id["stub-echo"].ok
    assert not by_id["hosted-x"].ok
    assert "unavailable" in by_id["hosted-x"].error
    assert "MISSING_KEY_FOR_TEST" in by_id["hosted-x"].error
