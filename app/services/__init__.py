"""Services: orchestration that wires the pipeline stages together."""

from __future__ import annotations

from app.services.comparison import Candidate, Comparison, compare, compare_with_providers

__all__ = ["Candidate", "Comparison", "compare", "compare_with_providers"]
