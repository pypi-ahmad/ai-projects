"""Alert persistence in data/obs.db: the alerts table, cooldown dedup, ack.

Owns all writes to the alerts table - stats.py/rules.py must not write
here directly. Next file to read: evaluator.py (the only caller of
in_cooldown + save_alert together).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from obs.alerts.models import Alert
from obs.export.sqlite import DEFAULT_DB_PATH

if TYPE_CHECKING:
    from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id TEXT PRIMARY KEY,
    rule TEXT NOT NULL,
    severity TEXT NOT NULL,
    route TEXT,
    model TEXT,
    window TEXT NOT NULL,
    value REAL NOT NULL,
    threshold REAL NOT NULL,
    trace_ids TEXT NOT NULL,
    ts TEXT NOT NULL,
    acked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_rule_route ON alerts(rule, route);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);
"""


def init_alerts_table(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)


def in_cooldown(
    rule: str,
    route: str | None,
    *,
    cooldown_minutes: int,
    db_path: Path = DEFAULT_DB_PATH,
) -> bool:
    """True if an alert for this rule+route already fired within the cooldown window.

    Deliberately keyed on (rule, route) only, not (rule, route, model): a
    route served by several models that all trip the same rule share one
    cooldown clock. See docs/ALERTS.md.
    """
    init_alerts_table(db_path)
    cutoff = (datetime.now(UTC) - timedelta(minutes=cooldown_minutes)).isoformat()
    with sqlite3.connect(db_path) as conn:
        # `route IS ?` (not `=`) so a bound NULL route matches NULL rows -
        # plain `=` never matches NULL in SQL.
        row = conn.execute(
            """SELECT 1 FROM alerts
               WHERE rule = ? AND route IS ? AND ts >= ?
               LIMIT 1""",
            (rule, route, cutoff),
        ).fetchone()
    return row is not None


def save_alert(alert: Alert, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    init_alerts_table(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO alerts
               (id, rule, severity, route, model, window, value, threshold, trace_ids, ts, acked)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                alert.id,
                alert.rule,
                alert.severity,
                alert.route,
                alert.model,
                alert.window,
                alert.value,
                alert.threshold,
                json.dumps(alert.trace_ids),
                alert.ts,
                int(alert.acked),
            ),
        )


def _row_to_alert(row: sqlite3.Row) -> Alert:
    return Alert(
        id=row["id"],
        rule=row["rule"],
        severity=row["severity"],
        route=row["route"],
        model=row["model"],
        window=row["window"],
        value=row["value"],
        threshold=row["threshold"],
        trace_ids=json.loads(row["trace_ids"]),
        ts=row["ts"],
        acked=bool(row["acked"]),
    )


def get_alert(alert_id: str, *, db_path: Path = DEFAULT_DB_PATH) -> Alert | None:
    init_alerts_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_alert(row) if row is not None else None


def list_alerts(*, acked: bool | None = None, db_path: Path = DEFAULT_DB_PATH) -> list[Alert]:
    init_alerts_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if acked is None:
            rows = conn.execute("SELECT * FROM alerts ORDER BY ts DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM alerts WHERE acked = ? ORDER BY ts DESC", (int(acked),)
            ).fetchall()
    finally:
        conn.close()
    return [_row_to_alert(r) for r in rows]


def ack_alert(alert_id: str, *, db_path: Path = DEFAULT_DB_PATH) -> None:
    init_alerts_table(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE alerts SET acked = 1 WHERE id = ?", (alert_id,))
