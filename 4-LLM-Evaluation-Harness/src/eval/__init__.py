"""Reduces a run's candidates/rule_scores/judge_scores into a RunSummary
(models.py) via summarize.py's summarize_run. Consumed next by src.gate.
"""

from src.eval.models import GroupSummary, RunSummary
from src.eval.summarize import render_markdown, summarize_run

__all__ = ["GroupSummary", "RunSummary", "render_markdown", "summarize_run"]
