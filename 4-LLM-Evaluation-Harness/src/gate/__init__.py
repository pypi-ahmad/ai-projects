"""Regression gate: compares a run's summary.json against config/gate.yaml and
an optional baselines/current.json. See evaluate.py for the pass/fail logic
and accept.py for how a baseline is produced.
"""

from src.gate.accept import build_baseline, write_baseline
from src.gate.evaluate import evaluate_gate
from src.gate.models import Baseline, BaselineConfig, GateConfig, GateFailure

__all__ = [
    "Baseline",
    "BaselineConfig",
    "GateConfig",
    "GateFailure",
    "build_baseline",
    "evaluate_gate",
    "write_baseline",
]
