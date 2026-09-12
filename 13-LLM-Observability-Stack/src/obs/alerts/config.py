"""Loads config/alerts.yaml into typed rule configs.

Pure config schema - no rule evaluation logic (see rules.py) and no
persistence (see store.py). Missing config/alerts.yaml is not an error:
load_alerts_config falls back to these class-level defaults. Next file to
read: rules.py (one check_* function per rule name here).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

ALERTS_CONFIG_PATH = Path("config/alerts.yaml")

Severity = Literal["critical", "warning", "info"]


class ErrorRateRule(BaseModel):
    enabled: bool = True
    window_n: int = 50
    threshold: float = 0.2
    severity: Severity = "critical"


class LatencyRegressionRule(BaseModel):
    enabled: bool = True
    window_n: int = 50
    k: float = 2.0
    severity: Severity = "warning"


class CostSumHourRule(BaseModel):
    enabled: bool = True
    budget_usd: float = 1.0
    severity: Severity = "warning"


class Ttft50Rule(BaseModel):
    enabled: bool = True
    window_n: int = 50
    threshold_ms: float = 2000.0
    severity: Severity = "warning"


class TrafficDropRule(BaseModel):
    enabled: bool = False
    window_minutes: int = 15
    baseline_window_minutes: int = 60
    drop_ratio: float = 0.2
    severity: Severity = "warning"


class UnpricedBurstRule(BaseModel):
    enabled: bool = False
    window_n: int = 50
    threshold: float = 0.5
    severity: Severity = "info"


class AlertRules(BaseModel):
    error_rate: ErrorRateRule = ErrorRateRule()
    latency_regression: LatencyRegressionRule = LatencyRegressionRule()
    cost_sum_hour: CostSumHourRule = CostSumHourRule()
    ttft_p50: Ttft50Rule = Ttft50Rule()
    traffic_drop: TrafficDropRule = TrafficDropRule()
    unpriced_burst: UnpricedBurstRule = UnpricedBurstRule()


class AlertsConfig(BaseModel):
    cooldown_minutes: int = 30
    rules: AlertRules = AlertRules()


def load_alerts_config(path: Path = ALERTS_CONFIG_PATH) -> AlertsConfig:
    if not path.exists():
        return AlertsConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AlertsConfig(**data)
