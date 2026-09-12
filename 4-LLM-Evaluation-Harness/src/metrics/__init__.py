"""Deterministic (rule-based) scoring. aggregate.score_case is the entry point;
rules.py has each metric's implementation, documented in docs/METRICS.md.
"""

from src.metrics.aggregate import score_case
from src.metrics.models import CaseScore, MetricResult

__all__ = ["CaseScore", "MetricResult", "score_case"]
