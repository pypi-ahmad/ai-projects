"""Public surface of the eval package — see runner.py for the actual
harness (`load_cases`/`run_eval`)."""

from .runner import EvalCaseResult, EvalSummary, load_cases, run_eval

__all__ = ["EvalCaseResult", "EvalSummary", "load_cases", "run_eval"]
