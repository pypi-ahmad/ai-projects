"""Outcome events: SQLite for queryable/updatable state, JSONL for an
append-only audit trail. `track` updates the SQLite row and appends a new
JSONL line — it never rewrites a previous line.

`user_key` is hashed before it touches either store; the raw value is
never persisted.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from promptreg.execute.models import ExecutionResult
from promptreg.outcomes.models import OutcomeEvent, OutcomeMetrics

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outcomes (
    request_id TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    user_key_hash TEXT NOT NULL,
    prompt_name TEXT NOT NULL,
    version INTEGER NOT NULL,
    arm TEXT,
    experiment_id INTEGER,
    latency_ms REAL NOT NULL,
    ok INTEGER NOT NULL,
    thumbs INTEGER,
    task_ok INTEGER,
    tokens_out INTEGER,
    custom_json TEXT NOT NULL DEFAULT '{}'
);
"""


def hash_user_key(user_key: str) -> str:
    return hashlib.sha256(user_key.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_event(row: sqlite3.Row) -> OutcomeEvent:
    return OutcomeEvent(
        request_id=row["request_id"],
        ts=row["ts"],
        user_key_hash=row["user_key_hash"],
        prompt_name=row["prompt_name"],
        version=row["version"],
        arm=row["arm"],
        experiment_id=row["experiment_id"],
        latency_ms=row["latency_ms"],
        ok=bool(row["ok"]),
        metrics=OutcomeMetrics(
            thumbs=row["thumbs"],
            task_ok=bool(row["task_ok"]) if row["task_ok"] is not None else None,
            tokens_out=row["tokens_out"],
            custom=json.loads(row["custom_json"]),
        ),
    )


class OutcomeStore:
    def __init__(self, db_path: str | Path, jsonl_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.jsonl_path = Path(jsonl_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _append_jsonl(self, event: OutcomeEvent, kind: str) -> None:
        line = {"event": kind, **json.loads(event.model_dump_json())}
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")

    def record(
        self,
        user_key: str,
        prompt_name: str,
        version: int,
        arm: str | None,
        experiment_id: int | None,
        result: ExecutionResult,
        *,
        request_id: str | None = None,
    ) -> OutcomeEvent:
        request_id = request_id or uuid.uuid4().hex
        user_key_hash = hash_user_key(user_key)
        now = _now()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT INTO outcomes
                       (request_id, ts, user_key_hash, prompt_name, version, arm,
                        experiment_id, latency_ms, ok)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    request_id,
                    now,
                    user_key_hash,
                    prompt_name,
                    version,
                    arm,
                    experiment_id,
                    result.latency_ms,
                    int(result.ok),
                ),
            )
        event = self.get(request_id)
        if event is None:
            msg = f"failed to record outcome {request_id}"
            raise RuntimeError(msg)
        self._append_jsonl(event, "record")
        return event

    def track(self, request_id: str, metrics: OutcomeMetrics) -> OutcomeEvent:
        with closing(self._connect()) as conn, conn:
            exists = conn.execute(
                "SELECT 1 FROM outcomes WHERE request_id = ?", (request_id,)
            ).fetchone()
            if exists is None:
                msg = f"no outcome {request_id}"
                raise KeyError(msg)
            conn.execute(
                """UPDATE outcomes SET thumbs = ?, task_ok = ?, tokens_out = ?, custom_json = ?
                   WHERE request_id = ?""",
                (
                    metrics.thumbs,
                    None if metrics.task_ok is None else int(metrics.task_ok),
                    metrics.tokens_out,
                    json.dumps(metrics.custom),
                    request_id,
                ),
            )
        event = self.get(request_id)
        if event is None:
            msg = f"failed to track outcome {request_id}"
            raise RuntimeError(msg)
        self._append_jsonl(event, "track")
        return event

    def get(self, request_id: str) -> OutcomeEvent | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM outcomes WHERE request_id = ?", (request_id,)
            ).fetchone()
        return _row_to_event(row) if row is not None else None

    def summary(self, experiment_id: int) -> dict[str, dict[str, float]]:
        """Per-arm descriptive counts for one experiment.

        count, ok, thumbs_up, thumbs_down, task_ok (raw counts) plus
        ok_rate, thumbs_net, avg_latency_ms, p50_latency_ms (derived).
        Deliberately just arithmetic on the raw counts/latencies — no
        significance testing, confidence intervals, or Bayesian inference.
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM outcomes WHERE experiment_id = ?", (experiment_id,)
            ).fetchall()
        arms: dict[str, dict[str, float]] = {}
        latencies: dict[str, list[float]] = {}
        for row in rows:
            arm = row["arm"] or "(none)"
            bucket = arms.setdefault(
                arm, {"count": 0, "ok": 0, "thumbs_up": 0, "thumbs_down": 0, "task_ok": 0}
            )
            bucket["count"] += 1
            bucket["ok"] += int(bool(row["ok"]))
            if row["thumbs"] == 1:
                bucket["thumbs_up"] += 1
            elif row["thumbs"] == -1:
                bucket["thumbs_down"] += 1
            if row["task_ok"]:
                bucket["task_ok"] += 1
            latencies.setdefault(arm, []).append(row["latency_ms"])
        for arm, bucket in arms.items():
            bucket["ok_rate"] = bucket["ok"] / bucket["count"]
            bucket["thumbs_net"] = bucket["thumbs_up"] - bucket["thumbs_down"]
            bucket["avg_latency_ms"] = sum(latencies[arm]) / bucket["count"]
            bucket["p50_latency_ms"] = statistics.median(latencies[arm])
        return arms
