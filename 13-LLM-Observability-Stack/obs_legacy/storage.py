"""SQLite + daily-rotated JSONL storage for traces and alerts.

Every trace/alert write goes to both stores in the same call: SQLite is the
query index the dashboard reads, JSONL is the append-only log for tailing
and backup. No separate sync job.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from obs_legacy.models import Alert, TraceRecord

DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "obs.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL UNIQUE,
    ts TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_hash TEXT,
    prompt_preview TEXT,
    response_hash TEXT,
    response_preview TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    latency_ms REAL,
    cost_usd REAL,
    priced INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_traces_ts ON traces(ts);
CREATE INDEX IF NOT EXISTS idx_traces_model ON traces(model);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    rule TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    llm_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);
"""


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(_SCHEMA)


def _jsonl_path(kind: str, ts: str) -> Path:
    day = ts[:10].replace("-", "")  # ts is ISO 8601, YYYY-MM-DD... -> YYYYMMDD
    directory = DATA_DIR / kind
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{day}.jsonl"


def _append_jsonl(kind: str, record: dict) -> None:
    path = _jsonl_path(kind, record["ts"])
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def save_trace(trace: TraceRecord) -> None:
    init_db()
    record = asdict(trace)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO traces
               (trace_id, ts, provider, model, prompt_hash, prompt_preview,
                response_hash, response_preview, tokens_in, tokens_out,
                latency_ms, cost_usd, priced, status, error)
               VALUES
               (:trace_id, :ts, :provider, :model, :prompt_hash, :prompt_preview,
                :response_hash, :response_preview, :tokens_in, :tokens_out,
                :latency_ms, :cost_usd, :priced, :status, :error)""",
            record,
        )
    _append_jsonl("traces", record)


def save_alert(alert: Alert) -> None:
    init_db()
    record = asdict(alert)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO alerts (trace_id, ts, rule, severity, message, llm_note)
               VALUES (:trace_id, :ts, :rule, :severity, :message, :llm_note)""",
            record,
        )
    _append_jsonl("alerts", record)


def load_traces(limit: int = 500) -> list[sqlite3.Row]:
    init_db()
    with get_connection() as conn:
        return conn.execute("SELECT * FROM traces ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()


def load_alerts(limit: int = 500) -> list[sqlite3.Row]:
    init_db()
    with get_connection() as conn:
        return conn.execute("SELECT * FROM alerts ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
