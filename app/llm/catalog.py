"""Model catalog: the set of models the product can run, loaded from config.

The catalog is data, not code. It lives in `models.toml` so a new model in some
future year is a config edit, not a release. Nothing above this layer hardcodes a
model name; callers ask the catalog and build a provider from what it returns.
This is the seam that lets the model landscape churn under a stable product.

Secrets never live here. A hosted model names the environment variable that holds
its key, and the key is read at runtime.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.llm.factory import ProviderConfig

# catalog.py -> app/llm -> app -> repo root, where models.toml lives.
_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "models.toml"


@dataclass(frozen=True)
class ModelSpec:
    """One model the product knows how to run.

    `id` is a stable slug and must not be renamed once shipped: runs, stored
    comparisons, and the frontend all key off it.
    """

    id: str
    display_name: str
    provider: str
    model: str = ""
    base_url: str | None = None
    api_key_env: str | None = None
    host: str = "http://localhost:11434"
    tier: str = "hosted"
    enabled: bool = True
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelSpec:
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"model {data.get('id', '?')!r} has unknown keys: {sorted(unknown)}")
        return cls(**data)

    def available(self) -> bool:
        """True when this model can actually be called right now.

        Local models are always available. A hosted model is available only when
        its API key is present in the environment, so the frontend can grey out a
        model whose key is not configured instead of failing at call time.
        """
        if self.api_key_env:
            return bool(os.environ.get(self.api_key_env))
        return True

    def to_provider_config(self) -> ProviderConfig:
        api_key = os.environ.get(self.api_key_env) if self.api_key_env else None
        return ProviderConfig(
            kind=self.provider,
            model=self.model,
            base_url=self.base_url,
            api_key=api_key,
            host=self.host,
        )


class ModelCatalog:
    """An index of model specs, loaded from a TOML file."""

    def __init__(self, specs: list[ModelSpec]) -> None:
        self._specs: dict[str, ModelSpec] = {}
        for spec in specs:
            if spec.id in self._specs:
                raise ValueError(f"duplicate model id in catalog: {spec.id!r}")
            self._specs[spec.id] = spec

    @classmethod
    def from_toml(cls, path: Path | str) -> ModelCatalog:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"model catalog not found: {path}")
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
        return cls([ModelSpec.from_dict(entry) for entry in data.get("model", [])])

    def get(self, model_id: str) -> ModelSpec:
        try:
            return self._specs[model_id]
        except KeyError:
            raise KeyError(f"no model with id {model_id!r}") from None

    def all(self) -> list[ModelSpec]:
        return list(self._specs.values())

    def enabled(self) -> list[ModelSpec]:
        return [s for s in self._specs.values() if s.enabled]

    def available(self) -> list[ModelSpec]:
        """Enabled models whose key (if any) is present. What the picker offers."""
        return [s for s in self._specs.values() if s.enabled and s.available()]

    def ids(self) -> list[str]:
        return list(self._specs)


@lru_cache(maxsize=1)
def default_catalog() -> ModelCatalog:
    """The catalog over the repo's own models.toml, loaded once."""
    return ModelCatalog.from_toml(_DEFAULT_PATH)
