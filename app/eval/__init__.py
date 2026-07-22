"""Evaluation harness: score a rewrite against its original, deterministically.

The scoreboard is prose quality and factual fidelity, exactly as the product
charter says. It is not a detector and produces no AI-probability score. Every
number here is a transparent, offline measurement, so a comparison between models
is reproducible and never drifts with a vendor's black box.
"""

from __future__ import annotations

from app.eval.evaluate import (
    Evaluation,
    Fidelity,
    Quality,
    VoiceMatch,
    evaluate,
)
from app.eval.judge import JudgeVerdict, judge_rewrites

__all__ = [
    "Evaluation",
    "Fidelity",
    "JudgeVerdict",
    "Quality",
    "VoiceMatch",
    "evaluate",
    "judge_rewrites",
]
