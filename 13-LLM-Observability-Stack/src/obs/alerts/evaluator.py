"""Core evaluation pass. Kept out of eval.py so `python -m obs.alerts.eval`
(a runnable module) is never also imported as a side effect of importing the
`obs.alerts` package - see docs/ALERTS.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from obs.alerts import stats, store
from obs.alerts.config import ALERTS_CONFIG_PATH, load_alerts_config
from obs.alerts.models import Alert
from obs.alerts.rules import RULE_CHECKS
from obs.export.sqlite import DEFAULT_DB_PATH

if TYPE_CHECKING:
    from pathlib import Path


def evaluate_once(
    *,
    config_path: Path = ALERTS_CONFIG_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    now: datetime | None = None,
    lookback_hours: int = 24,
) -> list[Alert]:
    """One evaluation pass over every (route, model) pair with recent activity."""
    if not db_path.exists():
        return []  # no traces recorded yet - nothing to evaluate

    now = now or datetime.now(UTC)
    cfg = load_alerts_config(config_path)
    since = (now - timedelta(hours=lookback_hours)).isoformat()
    pairs = stats.distinct_route_models(since=since, db_path=db_path)

    created: list[Alert] = []
    for route, model in pairs:
        for rule_name, check_fn in RULE_CHECKS.items():
            rule_cfg = getattr(cfg.rules, rule_name)
            if not rule_cfg.enabled:
                continue
            result = check_fn(route, model, rule_cfg, db_path=db_path, now=now)
            if result is None:
                continue
            # Cooldown is (rule, route) only (store.py), not (rule, route,
            # model) - within a single pass, the first (route, model) pair
            # to trip a rule for a given route sets that route's cooldown
            # for every other model sharing it too. distinct_route_models()
            # already excludes model=None pairs specifically to avoid one
            # such pair silently starving a real one.
            if store.in_cooldown(
                rule_name, route, cooldown_minutes=cfg.cooldown_minutes, db_path=db_path
            ):
                continue
            alert = Alert(
                rule=result.rule,
                severity=rule_cfg.severity,
                route=route,
                model=model,
                window=result.window,
                value=result.value,
                threshold=result.threshold,
                trace_ids=result.trace_ids,
            )
            store.save_alert(alert, db_path=db_path)
            created.append(alert)
    return created
