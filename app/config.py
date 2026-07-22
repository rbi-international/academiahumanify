"""Load environment variables from a .env file, with no third-party dependency.

Hosted-model keys are read from the environment. This lets a user keep them in a
local .env file (gitignored) instead of exporting them by hand each session.
A value already set in the real environment wins, so a shell export or a CI
secret always overrides the file.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping
from pathlib import Path

# config.py -> app -> repo root, where .env lives.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def load_env(
    path: str | Path | None = None,
    *,
    override: bool = False,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Read KEY=VALUE lines from a .env file into the environment.

    Blank lines, comments (#), and empty values are skipped. Quotes around a
    value are stripped. Existing variables are kept unless override is True.
    Returns the mapping that was applied. `environ` is injectable for testing.
    """

    env = os.environ if environ is None else environ
    env_path = Path(path) if path is not None else _REPO_ROOT / ".env"
    if not env_path.is_file():
        return {}

    applied: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or not value:
            continue
        if override or key not in env:
            env[key] = value
            applied[key] = value
    return applied
