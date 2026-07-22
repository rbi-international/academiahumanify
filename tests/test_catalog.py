"""Model catalog tests: loading, availability, and provider construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.llm.catalog import ModelCatalog, ModelSpec, default_catalog

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
model = "x-large"
base_url = "https://api.example.com/v1"
api_key_env = "EXAMPLE_API_KEY"
tier = "hosted"
enabled = true

[[model]]
id = "disabled-y"
display_name = "Disabled Y"
provider = "ollama"
model = "y"
enabled = false
"""


def _catalog(tmp_path: Path) -> ModelCatalog:
    path = tmp_path / "models.toml"
    path.write_text(_TOML, encoding="utf-8")
    return ModelCatalog.from_toml(path)


def test_loads_specs_from_toml(tmp_path: Path) -> None:
    cat = _catalog(tmp_path)
    assert set(cat.ids()) == {"stub-echo", "hosted-x", "disabled-y"}
    assert cat.get("hosted-x").model == "x-large"


def test_enabled_and_available_filtering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cat = _catalog(tmp_path)
    assert {s.id for s in cat.enabled()} == {"stub-echo", "hosted-x"}
    # Without the key, the hosted model is enabled but not available.
    monkeypatch.delenv("EXAMPLE_API_KEY", raising=False)
    assert {s.id for s in cat.available()} == {"stub-echo"}
    # With the key set, it becomes available.
    monkeypatch.setenv("EXAMPLE_API_KEY", "secret")
    assert {s.id for s in cat.available()} == {"stub-echo", "hosted-x"}


def test_to_provider_config_reads_key_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cat = _catalog(tmp_path)
    monkeypatch.setenv("EXAMPLE_API_KEY", "secret")
    config = cat.get("hosted-x").to_provider_config()
    assert config.kind == "openai_compat"
    assert config.base_url == "https://api.example.com/v1"
    assert config.api_key == "secret"


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        ModelSpec.from_dict({"id": "x", "display_name": "X", "provider": "stub", "bogus": 1})


def test_duplicate_id_is_rejected() -> None:
    spec = ModelSpec(id="dup", display_name="Dup", provider="stub")
    with pytest.raises(ValueError):
        ModelCatalog([spec, spec])


def test_missing_catalog_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        ModelCatalog.from_toml("no/such/models.toml")


def test_default_catalog_loads_and_has_a_local_baseline() -> None:
    cat = default_catalog()
    assert "stub-echo" in cat.ids()
    # The offline baseline is always available.
    assert any(s.id == "stub-echo" for s in cat.available())
