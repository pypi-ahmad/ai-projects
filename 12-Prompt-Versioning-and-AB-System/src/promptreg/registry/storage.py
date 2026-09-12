"""SQLite + on-disk registry: prompts, immutable versions, env pointers.

Prompt bodies live at ``<prompts_dir>/<prompt_name>/<version>.md`` and are
never overwritten — a new version always gets a new file. SQLite holds
everything else, including the sha256 of each body: `get` re-hashes the
file on disk and raises `IntegrityError` if it no longer matches.

No A/B here — `pointers` is a single version per (prompt, env). A running
experiment can override this pointer at resolve time; see
`promptreg.split.storage` (`ExperimentStore.resolve`) next.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from promptreg.registry.hashing import sha256_hex
from promptreg.registry.models import Env, Pointer, PromptConfig, Version

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prompts (
    name TEXT PRIMARY KEY,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS versions (
    prompt_id TEXT NOT NULL REFERENCES prompts(name),
    version INTEGER NOT NULL,
    label TEXT,
    sha256 TEXT NOT NULL,
    body_path TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    author TEXT NOT NULL,
    changelog TEXT NOT NULL,
    immutable INTEGER NOT NULL DEFAULT 1 CHECK (immutable = 1),
    PRIMARY KEY (prompt_id, version)
);

CREATE TABLE IF NOT EXISTS pointers (
    prompt_id TEXT NOT NULL REFERENCES prompts(name),
    env TEXT NOT NULL CHECK (env IN ('prod', 'staging')),
    version INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (prompt_id, env)
);

CREATE TABLE IF NOT EXISTS pointer_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id TEXT NOT NULL,
    env TEXT NOT NULL,
    version INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('set', 'rollback')),
    created_at TEXT NOT NULL
);
"""


class IntegrityError(Exception):
    """A version's on-disk body no longer matches its stored sha256."""


_HISTORY_NEEDED_FOR_ROLLBACK = 2


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Registry:
    """Owns the SQLite connection and the prompt-body file tree."""

    def __init__(self, db_path: str | Path, prompts_dir: str | Path) -> None:
        self.db_path = Path(db_path)
        self.prompts_dir = Path(prompts_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _body_path(self, name: str, version: int) -> Path:
        return self.prompts_dir / name / f"{version}.md"

    def publish(
        self,
        name: str,
        body: str,
        config: PromptConfig,
        changelog: str,
        author: str,
        *,
        description: str | None = None,
        label: str | None = None,
    ) -> Version:
        """Write a new immutable version. Never overwrites a prior one."""
        digest = sha256_hex(body)
        now = _now()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO prompts (name, description, created_at) VALUES (?, ?, ?)",
                (name, description, now),
            )
            next_version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next FROM versions WHERE prompt_id = ?",
                (name,),
            ).fetchone()["next"]
            body_path = self._body_path(name, next_version)
            body_path.parent.mkdir(parents=True, exist_ok=True)
            body_path.write_text(body, encoding="utf-8")
            conn.execute(
                """INSERT INTO versions
                       (prompt_id, version, label, sha256, body_path, config_json,
                        created_at, author, changelog, immutable)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    name,
                    next_version,
                    label,
                    digest,
                    str(body_path),
                    config.model_dump_json(),
                    now,
                    author,
                    changelog,
                ),
            )
        return self.get(name, next_version)

    def get(self, name: str, version: int) -> Version:
        """Read a version and verify its body against the stored hash."""
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM versions WHERE prompt_id = ? AND version = ?",
                (name, version),
            ).fetchone()
        if row is None:
            msg = f"no version {version} for prompt {name!r}"
            raise KeyError(msg)
        body = Path(row["body_path"]).read_text(encoding="utf-8")
        actual = sha256_hex(body)
        if actual != row["sha256"]:
            msg = (
                f"INTEGRITY: sha256 mismatch for {name!r} v{version}: "
                f"expected {row['sha256']}, got {actual}"
            )
            raise IntegrityError(msg)
        return Version(
            prompt_id=row["prompt_id"],
            version=row["version"],
            label=row["label"],
            sha256=row["sha256"],
            body_path=row["body_path"],
            config=PromptConfig.model_validate_json(row["config_json"]),
            created_at=row["created_at"],
            author=row["author"],
            changelog=row["changelog"],
            body=body,
        )

    def list_prompts(self) -> list[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT name FROM prompts ORDER BY name ASC").fetchall()
        return [row["name"] for row in rows]

    def list_versions(self, name: str) -> list[Version]:
        """Metadata for every version, oldest first. Does not touch disk."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM versions WHERE prompt_id = ? ORDER BY version ASC",
                (name,),
            ).fetchall()
        return [
            Version(
                prompt_id=row["prompt_id"],
                version=row["version"],
                label=row["label"],
                sha256=row["sha256"],
                body_path=row["body_path"],
                config=PromptConfig.model_validate_json(row["config_json"]),
                created_at=row["created_at"],
                author=row["author"],
                changelog=row["changelog"],
            )
            for row in rows
        ]

    def set_pointer(self, name: str, env: Env, version: int) -> Pointer:
        now = _now()
        with closing(self._connect()) as conn, conn:
            exists = conn.execute(
                "SELECT 1 FROM versions WHERE prompt_id = ? AND version = ?",
                (name, version),
            ).fetchone()
            if exists is None:
                msg = f"no version {version} for prompt {name!r}"
                raise KeyError(msg)
            conn.execute(
                """INSERT INTO pointers (prompt_id, env, version, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(prompt_id, env) DO UPDATE SET
                       version = excluded.version,
                       updated_at = excluded.updated_at""",
                (name, env, version, now),
            )
            conn.execute(
                """INSERT INTO pointer_history (prompt_id, env, version, action, created_at)
                   VALUES (?, ?, ?, 'set', ?)""",
                (name, env, version, now),
            )
        return Pointer(prompt_id=name, env=env, version=version, updated_at=now)

    def get_pointer(self, name: str, env: Env) -> Pointer | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM pointers WHERE prompt_id = ? AND env = ?",
                (name, env),
            ).fetchone()
        if row is None:
            return None
        return Pointer(
            prompt_id=row["prompt_id"],
            env=row["env"],
            version=row["version"],
            updated_at=row["updated_at"],
        )

    def rollback(self, name: str, env: Env) -> Pointer:
        """Move the pointer back to what it was before its current value.

        Never touches version rows or body files — only the pointer, plus
        an audit row in `pointer_history`.
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """SELECT version FROM pointer_history
                   WHERE prompt_id = ? AND env = ?
                   ORDER BY id DESC LIMIT 2""",
                (name, env),
            ).fetchall()
        if len(rows) < _HISTORY_NEEDED_FOR_ROLLBACK:
            msg = f"no previous pointer for {name!r}/{env}"
            raise ValueError(msg)
        previous_version = rows[1]["version"]
        now = _now()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT INTO pointers (prompt_id, env, version, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(prompt_id, env) DO UPDATE SET
                       version = excluded.version,
                       updated_at = excluded.updated_at""",
                (name, env, previous_version, now),
            )
            conn.execute(
                """INSERT INTO pointer_history (prompt_id, env, version, action, created_at)
                   VALUES (?, ?, ?, 'rollback', ?)""",
                (name, env, previous_version, now),
            )
        return Pointer(prompt_id=name, env=env, version=previous_version, updated_at=now)
