"""Rule checks. Each takes (route, model, its own rule config) and returns a
RuleResult if it fired, else None. See config/alerts.yaml and docs/ALERTS.md.

All six check_* functions share one signature (route, model, cfg, *,
db_path, now) so evaluator.py can dispatch through RULE_CHECKS uniformly
via getattr(config.rules, rule_name) - `cfg`'s concrete type differs per
function (see the TYPE_CHECKING imports), which is why RULE_CHECKS is typed
loosely as Callable[..., RuleResult | None] rather than a stricter Protocol
(a stricter shared Protocol can't express six different `cfg` types without
widening every function to accept `object`). `now` is accepted even where
unused (see the ARG001 noqas) purely to keep that shared signature - it's
how tests inject a fixed clock instead of datetime.now(UTC). Must not write
to the alerts table (store.py owns that) or read config/alerts.yaml
directly (config.py owns that). Next file to read: evaluator.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from obs.alerts import stats
from obs.export.sqlite import DEFAULT_DB_PATH

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from obs.alerts.config import (
        CostSumHourRule,
        ErrorRateRule,
        LatencyRegressionRule,
        TrafficDropRule,
        Ttft50Rule,
        UnpricedBurstRule,
    )


@dataclass
class RuleResult:
    rule: str
    value: float
    threshold: float
    window: str
    trace_ids: list[str]


def check_error_rate(
    route: str | None,
    model: str | None,
    cfg: ErrorRateRule,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    now: datetime | None = None,  # noqa: ARG001 - uniform RuleCheck signature
) -> RuleResult | None:
    rows = stats.fetch_window_rows(route, model, limit=cfg.window_n, db_path=db_path)
    s = stats.compute_window_stats(rows)
    if s.n == 0 or s.error_rate <= cfg.threshold:
        return None
    return RuleResult(
        rule="error_rate",
        value=s.error_rate,
        threshold=cfg.threshold,
        window=f"last_{cfg.window_n}",
        trace_ids=s.trace_ids,
    )


def check_latency_regression(
    route: str | None,
    model: str | None,
    cfg: LatencyRegressionRule,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    now: datetime | None = None,
) -> RuleResult | None:
    now = now or datetime.now(UTC)
    current = stats.compute_window_stats(
        stats.fetch_window_rows(route, model, limit=cfg.window_n, db_path=db_path)
    )
    if current.p95_latency_ms is None:
        return None

    today_start = now.strftime("%Y-%m-%dT00:00:00")
    yesterday_start = (now - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00")
    prev_day = stats.compute_window_stats(
        stats.fetch_window_rows(
            route, model, since=yesterday_start, until=today_start, db_path=db_path
        )
    )
    baseline = prev_day.p95_latency_ms
    baseline_desc = "prev_day_p95"

    # No previous-day data (e.g. this route/model is brand new): fall back
    # to the first hour ever recorded, using its p50 rather than p95 - a
    # small first-hour sample makes a p95 estimate too noisy to trust, but
    # a median is more robust with few points.
    if baseline is None:
        first_ts = stats.earliest_ts(route, model, db_path=db_path)
        if first_ts is not None:
            first_hour_until = (datetime.fromisoformat(first_ts) + timedelta(hours=1)).isoformat()
            first_hour = stats.compute_window_stats(
                stats.fetch_window_rows(
                    route, model, since=first_ts, until=first_hour_until, db_path=db_path
                )
            )
            baseline = first_hour.p50_latency_ms
            baseline_desc = "first_hour_p50"

    if baseline is None or baseline <= 0:
        return None

    threshold_value = cfg.k * baseline
    if current.p95_latency_ms <= threshold_value:
        return None
    return RuleResult(
        rule="latency_regression",
        value=current.p95_latency_ms,
        threshold=threshold_value,
        window=f"last_{cfg.window_n}_vs_{baseline_desc}",
        trace_ids=current.trace_ids,
    )


def check_cost_sum_hour(
    route: str | None,
    model: str | None,
    cfg: CostSumHourRule,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    now: datetime | None = None,
) -> RuleResult | None:
    now = now or datetime.now(UTC)
    hour_start = now.strftime("%Y-%m-%dT%H:00:00")
    rows = stats.fetch_window_rows(route, model, since=hour_start, db_path=db_path)
    total = sum(r["cost_est"] for r in rows if r["cost_est"] is not None)
    if total <= cfg.budget_usd:
        return None
    trace_ids = list(dict.fromkeys(r["trace_id"] for r in rows))[:5]
    return RuleResult(
        rule="cost_sum_hour",
        value=total,
        threshold=cfg.budget_usd,
        window="current_hour",
        trace_ids=trace_ids,
    )


def check_ttft_p50(
    route: str | None,
    model: str | None,
    cfg: Ttft50Rule,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    now: datetime | None = None,  # noqa: ARG001 - uniform RuleCheck signature
) -> RuleResult | None:
    rows = stats.fetch_window_rows(route, model, limit=cfg.window_n, db_path=db_path)
    s = stats.compute_window_stats(rows)
    if s.ttft_p50_ms is None or s.ttft_p50_ms <= cfg.threshold_ms:
        return None
    return RuleResult(
        rule="ttft_p50",
        value=s.ttft_p50_ms,
        threshold=cfg.threshold_ms,
        window=f"last_{cfg.window_n}",
        trace_ids=s.trace_ids,
    )


def check_traffic_drop(
    route: str | None,
    model: str | None,
    cfg: TrafficDropRule,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    now: datetime | None = None,
) -> RuleResult | None:
    now = now or datetime.now(UTC)
    current_since = (now - timedelta(minutes=cfg.window_minutes)).isoformat()
    baseline_since = (now - timedelta(minutes=cfg.baseline_window_minutes)).isoformat()

    current_rows = stats.fetch_window_rows(route, model, since=current_since, db_path=db_path)
    baseline_rows = stats.fetch_window_rows(
        route, model, since=baseline_since, until=current_since, db_path=db_path
    )
    if not baseline_rows:
        return None

    baseline_rate = len(baseline_rows) / cfg.baseline_window_minutes
    current_rate = len(current_rows) / cfg.window_minutes
    if baseline_rate <= 0:
        return None
    ratio = current_rate / baseline_rate
    if ratio >= cfg.drop_ratio:
        return None
    trace_ids = list(dict.fromkeys(r["trace_id"] for r in current_rows))[:5]
    return RuleResult(
        rule="traffic_drop",
        value=ratio,
        threshold=cfg.drop_ratio,
        window=f"{cfg.window_minutes}m_vs_{cfg.baseline_window_minutes}m",
        trace_ids=trace_ids,
    )


def check_unpriced_burst(
    route: str | None,
    model: str | None,
    cfg: UnpricedBurstRule,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    now: datetime | None = None,  # noqa: ARG001 - uniform RuleCheck signature
) -> RuleResult | None:
    rows = stats.fetch_window_rows(route, model, limit=cfg.window_n, db_path=db_path)
    s = stats.compute_window_stats(rows)
    if s.unpriced_fraction is None or s.unpriced_fraction <= cfg.threshold:
        return None
    return RuleResult(
        rule="unpriced_burst",
        value=s.unpriced_fraction,
        threshold=cfg.threshold,
        window=f"last_{cfg.window_n}",
        trace_ids=s.trace_ids,
    )


RULE_CHECKS: dict[str, Callable[..., RuleResult | None]] = {
    "error_rate": check_error_rate,
    "latency_regression": check_latency_regression,
    "cost_sum_hour": check_cost_sum_hour,
    "ttft_p50": check_ttft_p50,
    "traffic_drop": check_traffic_drop,
    "unpriced_burst": check_unpriced_burst,
}
