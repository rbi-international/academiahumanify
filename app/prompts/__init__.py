"""Prompt library: versioned prompt files loaded by id and version.

Prompts live on disk under `prompts/`, not as strings in Python, because they
are product logic that changes more often than code. This package loads them,
gives each a checksum so a changed prompt is visible in the run log, and
composes the rewrite system prompt from its base plus the chosen intensity,
style, and optional field example.
"""

from __future__ import annotations

from app.prompts.registry import (
    Discipline,
    Prompt,
    PromptRef,
    PromptRegistry,
    RenderedPrompt,
    StyleVariant,
    compose_rewrite_system,
    default_registry,
)

__all__ = [
    "Discipline",
    "Prompt",
    "PromptRef",
    "PromptRegistry",
    "RenderedPrompt",
    "StyleVariant",
    "compose_rewrite_system",
    "default_registry",
]
