"""Experiments + sticky assignments: hash-based weighted traffic splits.

Shares the registry's SQLite file (pass the same `db_path`) so arm versions
and prompts can be foreign-key-checked. Construct the `Registry` for that
db_path first — this store relies on its `prompts`/`versions` tables
already existing. `resolve()` is the fan-in point callers actually use;
see `promptreg.outcomes.storage` (`OutcomeStore.record`) next for what
happens to its result.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from promptreg.registry.models import Env
from promptreg.registry.storage import Registry
from promptreg.split.models import (
    BUCKET_SPACE,
    Arm,
    Assignment,
    Experiment,
    Resolution,
    Status,
    validate_arms,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    prompt_name TEXT NOT NULL REFERENCES prompts(name),
    status TEXT NOT NULL CHECK (status IN ('draft', 'running', 'paused', 'stopped')),
    arms_json TEXT NOT NULL,
    sticky_salt TEXT NOT NULL,
    start_at TEXT,
    end_at TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS one_running_experiment_per_prompt
    ON experiments (prompt_name)
    WHERE status = 'running';

CREATE TABLE IF NOT EXISTS assignments (
    experiment_id INTEGER NOT NULL REFERENCES experiments(id),
    user_key TEXT NOT NULL,
    arm TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (experiment_id, user_key)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _bucket_for(user_key: str, salt: str) -> int:
    digest = hashlib.sha256(f"{user_key}{salt}".encode()).hexdigest()
    return int(digest, 16) % BUCKET_SPACE


def _pick_arm(arms: list[Arm], bucket: int) -> Arm:
    cumulative = 0
    for arm in arms:
        cumulative += arm.weight
        if bucket < cumulative:
            return arm
    msg = f"arms do not cover bucket {bucket} (weights must sum to {BUCKET_SPACE})"
    raise ValueError(msg)


def _experiment_from_row(row: sqlite3.Row) -> Experiment:
    arms = [Arm(**a) for a in json.loads(row["arms_json"])]
    return Experiment(
        id=row["id"],
        name=row["name"],
        prompt_name=row["prompt_name"],
        status=row["status"],
        arms=arms,
        sticky_salt=row["sticky_salt"],
        start_at=row["start_at"],
        end_at=row["end_at"],
        created_at=row["created_at"],
    )


class ExperimentStore:
    """Owns experiments/assignments in the same SQLite file as the registry."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def create_experiment(
        self,
        name: str,
        prompt_name: str,
        arms: list[Arm],
        *,
        sticky_salt: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> Experiment:
        """Create a `draft` experiment. `set_status` moves it to `running`."""
        validate_arms(arms)
        now = _now()
        with closing(self._connect()) as conn, conn:
            if (
                conn.execute("SELECT 1 FROM prompts WHERE name = ?", (prompt_name,)).fetchone()
                is None
            ):
                msg = f"no prompt {prompt_name!r}"
                raise KeyError(msg)
            for arm in arms:
                if (
                    conn.execute(
                        "SELECT 1 FROM versions WHERE prompt_id = ? AND version = ?",
                        (prompt_name, arm.version),
                    ).fetchone()
                    is None
                ):
                    msg = f"no version {arm.version} for prompt {prompt_name!r} (arm {arm.name!r})"
                    raise KeyError(msg)
            cursor = conn.execute(
                """INSERT INTO experiments
                       (name, prompt_name, status, arms_json, sticky_salt,
                        start_at, end_at, created_at)
                   VALUES (?, ?, 'draft', ?, ?, ?, ?, ?)""",
                (
                    name,
                    prompt_name,
                    json.dumps([arm.model_dump() for arm in arms]),
                    sticky_salt or secrets.token_hex(8),
                    start_at.isoformat() if start_at else None,
                    end_at.isoformat() if end_at else None,
                    now,
                ),
            )
            experiment_id = cursor.lastrowid
        if experiment_id is None:
            msg = "insert into experiments did not return a rowid"
            raise RuntimeError(msg)
        return self.get_experiment(experiment_id)

    def get_experiment(self, experiment_id: int) -> Experiment:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
        if row is None:
            msg = f"no experiment {experiment_id}"
            raise KeyError(msg)
        return _experiment_from_row(row)

    def list_experiments(self, prompt_name: str) -> list[Experiment]:
        """Every experiment for a prompt, most recent first."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM experiments WHERE prompt_name = ? ORDER BY id DESC",
                (prompt_name,),
            ).fetchall()
        return [_experiment_from_row(row) for row in rows]

    def set_status(self, experiment_id: int, status: Status) -> Experiment:
        """`running` is exclusive per prompt — starting a second one errors."""
        with closing(self._connect()) as conn, conn:
            if (
                conn.execute("SELECT 1 FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
                is None
            ):
                msg = f"no experiment {experiment_id}"
                raise KeyError(msg)
            if status == "running":
                prompt_name = conn.execute(
                    "SELECT prompt_name FROM experiments WHERE id = ?", (experiment_id,)
                ).fetchone()["prompt_name"]
                other_running = conn.execute(
                    """SELECT id FROM experiments
                       WHERE prompt_name = ? AND status = 'running' AND id != ?""",
                    (prompt_name, experiment_id),
                ).fetchone()
                if other_running is not None:
                    msg = f"prompt {prompt_name!r} already has a running experiment"
                    raise ValueError(msg)
            conn.execute("UPDATE experiments SET status = ? WHERE id = ?", (status, experiment_id))
        return self.get_experiment(experiment_id)

    def _active_experiment(self, prompt_name: str) -> Experiment | None:
        """Most recent running/paused experiment for a prompt, if any."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT * FROM experiments
                   WHERE prompt_name = ? AND status IN ('running', 'paused')
                   ORDER BY id DESC LIMIT 1""",
                (prompt_name,),
            ).fetchone()
        return _experiment_from_row(row) if row is not None else None

    def _assignment(self, experiment_id: int, user_key: str) -> Assignment | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM assignments WHERE experiment_id = ? AND user_key = ?",
                (experiment_id, user_key),
            ).fetchone()
        if row is None:
            return None
        return Assignment(
            experiment_id=row["experiment_id"],
            user_key=row["user_key"],
            arm=row["arm"],
            version=row["version"],
            created_at=row["created_at"],
        )

    def _assign(self, experiment: Experiment, user_key: str) -> Assignment:
        """First assignment wins: concurrent callers race an INSERT OR IGNORE,
        then both re-read — so every caller ends up with the same, first-in row."""
        chosen = _pick_arm(experiment.arms, _bucket_for(user_key, experiment.sticky_salt))
        now = _now()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT OR IGNORE INTO assignments
                       (experiment_id, user_key, arm, version, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (experiment.id, user_key, chosen.name, chosen.version, now),
            )
        assignment = self._assignment(experiment.id, user_key)
        if assignment is None:
            msg = f"failed to assign {user_key!r} in experiment {experiment.id}"
            raise RuntimeError(msg)
        return assignment

    def resolve(self, registry: Registry, prompt_name: str, user_key: str, env: Env) -> Resolution:
        """name + user_key + env -> Resolution.

        A running/paused experiment's sticky assignments always win. A
        running experiment additionally creates new ones. Everything else
        (draft, stopped, no experiment, or a paused one with no prior
        assignment for this user_key) falls through to the plain pointer.
        """
        experiment = self._active_experiment(prompt_name)
        if experiment is not None:
            existing = self._assignment(experiment.id, user_key)
            if existing is not None:
                return Resolution(
                    version=existing.version,
                    arm=existing.arm,
                    experiment_id=experiment.id,
                    reason="experiment_sticky",
                )
            if experiment.status == "running":
                assignment = self._assign(experiment, user_key)
                return Resolution(
                    version=assignment.version,
                    arm=assignment.arm,
                    experiment_id=experiment.id,
                    reason="experiment_new",
                )
        pointer = registry.get_pointer(prompt_name, env)
        if pointer is None:
            msg = f"no pointer set for {prompt_name!r}/{env}"
            raise KeyError(msg)
        return Resolution(version=pointer.version, arm=None, experiment_id=None, reason="pointer")
