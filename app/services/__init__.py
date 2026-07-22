"""Services: orchestration that wires the pipeline stages together."""

from __future__ import annotations

from app.services.comparison import Candidate, Comparison, compare, compare_with_providers
from app.services.orchestrator import RunResult, run_pipeline

__all__ = [
    "Candidate",
    "Comparison",
    "RunResult",
    "compare",
    "compare_with_providers",
    "run_pipeline",
]
