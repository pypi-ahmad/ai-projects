"""Episodic memory: timestamped event log in SQLite.

Keyword search uses FTS5 -- verified available in this Windows Python's
stdlib sqlite3 (3.53.1, see docs/RUNBOOK.md). No LIKE fallback: if a
deployment's sqlite3 lacks FTS5, table creation fails loudly at startup
rather than silently degrading search quality.

Must not: return a row from a different session_id than the one asked
for -- every read method filters on it, and that filter is not optional
anywhere in this file.

Next: src/memory/semantic.py -- where distilled episodes end up.
"""

from __future__ import annotations  # EpisodicMemory.list() shadows builtin list in annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from memory import config
from memory.working import count_tokens

EpisodeType = Literal["utterance", "tool", "decision", "compress_summary"]

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('utterance', 'tool', 'decision', 'compress_summary')),
  text TEXT NOT NULL,
  token_count INTEGER NOT NULL,
  refs TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(refs)),
  salience REAL NOT NULL DEFAULT 0.5 CHECK (salience >= 0 AND salience <= 1),
  pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_episodes_session_ts ON episodes(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_episodes_session_salience ON episodes(session_id, salience, ts);

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
  id UNINDEXED,
  session_id UNINDEXED,
  text,
  content='episodes',
  content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS episodes_fts_insert AFTER INSERT ON episodes BEGIN
  INSERT INTO episodes_fts(rowid, id, session_id, text)
  VALUES (new.rowid, new.id, new.session_id, new.text);
END;

CREATE TRIGGER IF NOT EXISTS episodes_fts_delete AFTER DELETE ON episodes BEGIN
  DELETE FROM episodes_fts WHERE rowid = old.rowid;
END;
"""


class Episode(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: EpisodeType
    text: str
    token_count: int
    refs: list[str] = Field(default_factory=list)
    salience: float = Field(default=0.5, ge=0, le=1)
    pinned: bool = False

    @classmethod
    def create(
        cls,
        session_id: str,
        type: EpisodeType,
        text: str,
        *,
        refs: list[str] | None = None,
        salience: float = 0.5,
        pinned: bool = False,
    ) -> "Episode":
        """Convenience constructor: computes token_count via count_tokens(text)."""
        return cls(
            session_id=session_id,
            type=type,
            text=text,
            token_count=count_tokens(text),
            refs=refs or [],
            salience=salience,
            pinned=pinned,
        )


class EvictionPolicy(BaseModel):
    """Data only. salience_threshold has no library default -- pick one deliberately."""

    max_rows: int | None = None
    max_age_days: float | None = None
    salience_threshold: float = Field(ge=0, le=1)


_FTS_TOKEN_RE = re.compile(r"\w+")


def _to_fts_query(raw: str) -> str | None:
    """Bare word tokens ORed together -- loose recall-style matching, and
    the only thing guaranteed not to trip FTS5's own query syntax. None
    means "nothing to search for" (caller should return no results)."""
    tokens = _FTS_TOKEN_RE.findall(raw)
    return " OR ".join(tokens) if tokens else None


def _row_to_episode(row: sqlite3.Row) -> Episode:
    return Episode(
        id=row["id"],
        session_id=row["session_id"],
        ts=datetime.fromisoformat(row["ts"]),
        type=row["type"],
        text=row["text"],
        token_count=row["token_count"],
        refs=json.loads(row["refs"]),
        salience=row["salience"],
        pinned=bool(row["pinned"]),
    )


class EpisodicMemory:
    def __init__(self, db_path: Path = config.SQLITE_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: Streamlit's @st.cache_resource keeps one
        # EpisodicMemory across reruns, but reruns can land on a different
        # worker thread than the one that opened this connection.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def write(self, episode: Episode) -> None:
        self._conn.execute(
            """
            INSERT INTO episodes (id, session_id, ts, type, text, token_count, refs, salience, pinned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode.id,
                episode.session_id,
                episode.ts.isoformat(),
                episode.type,
                episode.text,
                episode.token_count,
                json.dumps(episode.refs),
                episode.salience,
                int(episode.pinned),
            ),
        )
        self._conn.commit()

    def list(
        self,
        session_id: str,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Episode]:
        """Episodes for one session, oldest first. Never sees other sessions."""
        query = "SELECT * FROM episodes WHERE session_id = ?"
        params: list = [session_id]
        if since is not None:
            query += " AND ts >= ?"
            params.append(since.isoformat())
        query += " ORDER BY ts ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_episode(row) for row in rows]

    def search_keyword(self, session_id: str, query: str, limit: int = 20) -> list[Episode]:
        """FTS5 keyword search over `text`, ranked, scoped to one session.

        `query` is reduced to bare word tokens ORed together before hitting
        FTS5: its query syntax treats punctuation as operators, so a raw
        natural-language question (e.g. ending in "?") is a syntax error
        otherwise -- found by actually running a real query through the
        Phase 6 recall() path, not by inspection."""
        fts_query = _to_fts_query(query)
        if fts_query is None:
            return []
        matches = self._conn.execute(
            """
            SELECT id FROM episodes_fts
            WHERE session_id = ? AND episodes_fts MATCH ?
            ORDER BY bm25(episodes_fts)
            LIMIT ?
            """,
            (session_id, fts_query, limit),
        ).fetchall()
        ids = [row["id"] for row in matches]
        if not ids:
            return []
        rank = {episode_id: i for i, episode_id in enumerate(ids)}
        placeholders = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT * FROM episodes WHERE id IN ({placeholders})", ids
        ).fetchall()
        rows = sorted(rows, key=lambda row: rank[row["id"]])
        return [_row_to_episode(row) for row in rows]

    def evict(self, session_id: str, policy: EvictionPolicy) -> int:
        """Apply policy to one session. Never removes a pinned or
        salience >= threshold row, even if the session stays over cap.
        Among removable rows, evicts lowest-salience-then-oldest first.
        """
        deleted = 0
        if policy.max_age_days is not None:
            # ts is compared as an ISO-8601 string (`ts < ?`), not parsed --
            # only valid because every stored ts is UTC with the same
            # isoformat() layout, which sorts identically to chronological order.
            cutoff = datetime.now(timezone.utc) - timedelta(days=policy.max_age_days)
            deleted += self._delete_removable(
                session_id,
                policy,
                "ts < ?",
                (cutoff.isoformat(),),
            )
        if policy.max_rows is not None:
            deleted += self._trim_to_max_rows(session_id, policy)
        return deleted

    def _delete_removable(
        self,
        session_id: str,
        policy: EvictionPolicy,
        extra_where: str,
        extra_params: tuple,
    ) -> int:
        rows = self._conn.execute(
            f"""
            SELECT id FROM episodes
            WHERE session_id = ? AND pinned = 0 AND salience < ? AND {extra_where}
            """,
            (session_id, policy.salience_threshold, *extra_params),
        ).fetchall()
        ids = [row["id"] for row in rows]
        self._delete_ids(ids)
        return len(ids)

    def _trim_to_max_rows(self, session_id: str, policy: EvictionPolicy) -> int:
        total = self._conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE session_id = ?", (session_id,)
        ).fetchone()[0]
        overflow = total - policy.max_rows
        if overflow <= 0:
            return 0
        rows = self._conn.execute(
            """
            SELECT id FROM episodes
            WHERE session_id = ? AND pinned = 0 AND salience < ?
            ORDER BY salience ASC, ts ASC
            LIMIT ?
            """,
            (session_id, policy.salience_threshold, overflow),
        ).fetchall()
        ids = [row["id"] for row in rows]
        self._delete_ids(ids)
        return len(ids)

    def _delete_ids(self, ids: list[str]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        self._conn.execute(f"DELETE FROM episodes WHERE id IN ({placeholders})", ids)
        self._conn.commit()
