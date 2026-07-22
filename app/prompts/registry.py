"""Load, checksum, and compose versioned prompt files.

A prompt's identity is its path under `prompts/` without the version suffix, so
`prompts/system/rewrite.v1.md` has id `system/rewrite` at version 1. Every load
is hashed, so the exact prompt text behind a run is recorded and a silent edit
shows up as a changed checksum in the log.

The registry is deterministic and reads only local files, so it needs no network
and is fully testable.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

from app.pipeline.base import Intensity

# `<name>.v<version>.md` or `.txt`. The name may itself contain dots.
_FILENAME = re.compile(r"^(?P<name>.+)\.v(?P<version>\d+)\.(?:md|txt)$")

# Default location of the prompt files: the repo-root `prompts/` directory.
# registry.py -> app/prompts -> app -> repo root.
_DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "prompts"


class StyleVariant(Enum):
    """Voice registers the rewrite prompt can request."""

    FORMAL_CONSERVATIVE = "formal_conservative"
    MODERN_INTERDISCIPLINARY = "modern_interdisciplinary"


class Discipline(Enum):
    """Fields with a tailored before/after example."""

    CS = "cs"
    BIOLOGY = "biology"
    PHYSICS = "physics"
    SOCIAL_SCIENCE = "social_science"


@dataclass(frozen=True)
class Prompt:
    """One loaded prompt file, with the checksum of its text."""

    id: str
    version: int
    text: str
    checksum: str  # full sha256 hex of the normalised text
    path: str

    @property
    def short_checksum(self) -> str:
        return self.checksum[:12]

    def ref(self) -> PromptRef:
        return PromptRef(id=self.id, version=self.version, checksum=self.checksum)


@dataclass(frozen=True)
class PromptRef:
    """A pointer recorded in the run log: which prompt, which version, which
    exact bytes."""

    id: str
    version: int
    checksum: str


@dataclass(frozen=True)
class RenderedPrompt:
    """A composed prompt plus the refs of every fragment that went into it."""

    text: str
    refs: tuple[PromptRef, ...]


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class PromptRegistry:
    """An index of every prompt file under a root directory."""

    def __init__(self, root: Path | str = _DEFAULT_ROOT) -> None:
        self.root = Path(root)
        self._by_id: dict[str, dict[int, Prompt]] = {}
        self._load()

    def _load(self) -> None:
        if not self.root.is_dir():
            raise FileNotFoundError(f"prompt root does not exist: {self.root}")
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            match = _FILENAME.match(path.name)
            if not match:
                continue
            rel = path.relative_to(self.root)
            parent = rel.parent.as_posix()
            name = match.group("name")
            prompt_id = name if parent == "." else f"{parent}/{name}"
            version = int(match.group("version"))
            # read_text uses universal newlines, so a CRLF checkout still hashes
            # to the same value as the LF original.
            text = path.read_text(encoding="utf-8")
            prompt = Prompt(
                id=prompt_id,
                version=version,
                text=text,
                checksum=_checksum(text),
                path=str(path),
            )
            self._by_id.setdefault(prompt_id, {})[version] = prompt

    def get(self, prompt_id: str, version: int | None = None) -> Prompt:
        """Return a prompt by id, defaulting to its highest version."""
        versions = self._by_id.get(prompt_id)
        if not versions:
            raise KeyError(f"no prompt with id {prompt_id!r}")
        if version is None:
            version = max(versions)
        if version not in versions:
            raise KeyError(f"prompt {prompt_id!r} has no version {version}")
        return versions[version]

    def ref(self, prompt_id: str, version: int | None = None) -> PromptRef:
        return self.get(prompt_id, version).ref()

    def ids(self) -> list[str]:
        return sorted(self._by_id)

    def all(self) -> list[Prompt]:
        return [p for versions in self._by_id.values() for p in versions.values()]


@lru_cache(maxsize=1)
def default_registry() -> PromptRegistry:
    """The registry over the repo's own `prompts/` directory, loaded once."""
    return PromptRegistry(_DEFAULT_ROOT)


def compose_rewrite_system(
    intensity: Intensity,
    style: StyleVariant,
    discipline: Discipline | None = None,
    *,
    registry: PromptRegistry | None = None,
) -> RenderedPrompt:
    """Assemble the rewrite system prompt from its parts.

    Slots the chosen intensity and style directives into the base prompt, and
    appends a field example when a discipline is given. Returns the text plus a
    ref for every fragment used, so the run log can name and checksum exactly
    what the model was shown.
    """

    reg = registry or default_registry()

    base = reg.get("system/rewrite")
    inten = reg.get(f"system/intensity/{intensity.value}")
    styl = reg.get(f"system/style/{style.value}")

    text = base.text.replace("{{INTENSITY}}", inten.text.strip())
    text = text.replace("{{STYLE}}", styl.text.strip())

    refs = [base.ref(), inten.ref(), styl.ref()]

    if discipline is not None:
        example = reg.get(f"fewshot/{discipline.value}")
        text = (
            text.rstrip()
            + "\n\nExample of the transformation in this field:\n\n"
            + example.text.strip()
            + "\n"
        )
        refs.append(example.ref())

    if "{{" in text or "}}" in text:
        # A slot was left unfilled: the base prompt drifted from the composer.
        raise ValueError("rewrite prompt has unfilled template slots")

    return RenderedPrompt(text=text, refs=tuple(refs))
