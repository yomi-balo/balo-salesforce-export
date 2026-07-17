"""SQLite log of every payload sent to sf-middleware-api.

Schema and intent are documented in REFACTOR_PLAN.md.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

DEFAULT_DB_PATH = os.path.join("output", "sync.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_events (
  id            INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,
  sf_object     TEXT NOT NULL,
  route         TEXT NOT NULL,
  balo_id       TEXT NOT NULL,
  payload       TEXT NOT NULL,
  sources       TEXT NOT NULL,
  http_status   INTEGER,
  job_id        TEXT,
  response_body TEXT,
  duration_ms   INTEGER,
  sf_status     TEXT DEFAULT 'pending',
  sf_error      TEXT
);
CREATE INDEX IF NOT EXISTS idx_balo_id ON sync_events(balo_id);
CREATE INDEX IF NOT EXISTS idx_job_id  ON sync_events(job_id);
CREATE INDEX IF NOT EXISTS idx_status  ON sync_events(sf_status);

CREATE TABLE IF NOT EXISTS sync_runs (
  id                  INTEGER PRIMARY KEY,
  route               TEXT NOT NULL,
  started_at          TEXT NOT NULL,
  completed_at        TEXT,
  modified_since      TEXT,
  records_sent        INTEGER DEFAULT 0,
  records_skipped     INTEGER DEFAULT 0,
  notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_runs_route ON sync_runs(route, completed_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SyncLog:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        # WAL lets inspect.py read while sync.py is mid-run.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SyncLog":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --- sync_events --------------------------------------------------------

    def log_send(
        self,
        *,
        sf_object: str,
        route: str,
        balo_id: str,
        payload: dict,
        sources: Iterable[dict],
    ) -> int:
        """Insert a pending row before the HTTP call. Returns the event id."""
        cur = self._conn.execute(
            """
            INSERT INTO sync_events
                (ts, sf_object, route, balo_id, payload, sources, sf_status)
            VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                _now(),
                sf_object,
                route,
                balo_id,
                json.dumps(payload, default=str, ensure_ascii=False),
                json.dumps(list(sources), default=str, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_result(
        self,
        event_id: int,
        *,
        http_status: int | None,
        job_id: str | None,
        response_body: str | None,
        duration_ms: int | None,
    ) -> None:
        self._conn.execute(
            """
            UPDATE sync_events
               SET http_status = ?, job_id = ?, response_body = ?, duration_ms = ?
             WHERE id = ?
            """,
            (http_status, job_id, response_body, duration_ms, event_id),
        )
        self._conn.commit()

    def update_status(
        self,
        event_id: int,
        *,
        sf_status: str,
        sf_error: str | None = None,
    ) -> None:
        """Update terminal SF status. Typically called manually or by a reconciler."""
        self._conn.execute(
            "UPDATE sync_events SET sf_status = ?, sf_error = ? WHERE id = ?",
            (sf_status, sf_error, event_id),
        )
        self._conn.commit()

    def lookup(self, balo_id: str) -> list[dict[str, Any]]:
        """Return every event row for a balo_id, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM sync_events WHERE balo_id = ? ORDER BY id DESC",
            (balo_id,),
        ).fetchall()
        return [self._hydrate_event(r) for r in rows]

    def already_sent(self, balo_id: str, route: str) -> bool:
        """True if a successful (http 202) send for this balo_id+route exists."""
        row = self._conn.execute(
            """
            SELECT 1 FROM sync_events
             WHERE balo_id = ? AND route = ? AND http_status = 202
             LIMIT 1
            """,
            (balo_id, route),
        ).fetchone()
        return bool(row)

    def last_successful_payload(self, balo_id: str, route: str) -> dict | None:
        """Return the payload from the most recent 202 send, or None.

        Used by sync.py to diff the current Bubble payload against the last
        successful send so we can skip unchanged records and only PATCH
        changed fields (preserving SF-side edits on untouched fields).
        """
        row = self._conn.execute(
            """
            SELECT payload FROM sync_events
             WHERE balo_id = ? AND route = ? AND http_status = 202
             ORDER BY id DESC LIMIT 1
            """,
            (balo_id, route),
        ).fetchone()
        if not row or not row["payload"]:
            return None
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError:
            return None

    def list_by_status(self, sf_status: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM sync_events WHERE sf_status = ? ORDER BY id DESC",
            (sf_status,),
        ).fetchall()
        return [self._hydrate_event(r) for r in rows]

    @staticmethod
    def _hydrate_event(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for k in ("payload", "sources"):
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except json.JSONDecodeError:
                    pass
        return d

    # --- sync_runs ----------------------------------------------------------

    def start_run(self, route: str, modified_since: str | None, notes: str | None = None) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO sync_runs (route, started_at, modified_since, notes)
            VALUES (?, ?, ?, ?)
            """,
            (route, _now(), modified_since, notes),
        )
        self._conn.commit()
        return cur.lastrowid

    def complete_run(
        self,
        run_id: int,
        *,
        records_sent: int,
        records_skipped: int,
    ) -> None:
        self._conn.execute(
            """
            UPDATE sync_runs
               SET completed_at = ?, records_sent = ?, records_skipped = ?
             WHERE id = ?
            """,
            (_now(), records_sent, records_skipped, run_id),
        )
        self._conn.commit()

    def latest_cursor(self, route: str) -> str | None:
        """started_at of the most recent **completed** run for this route.

        Using started_at (not completed_at) closes a race: if a row is
        modified in Bubble mid-run, after the fetcher has already pulled
        that table, a completed_at-based cursor would miss it next run.
        started_at is always <= the timestamps of every Bubble record the
        fetch could have included, so any mid-run modification gets picked
        up next time. Already-sent rows are then short-circuited by
        already_sent().
        """
        row = self._conn.execute(
            """
            SELECT started_at FROM sync_runs
             WHERE route = ? AND completed_at IS NOT NULL
             ORDER BY started_at DESC
             LIMIT 1
            """,
            (route,),
        ).fetchone()
        return row["started_at"] if row else None


@contextmanager
def open_log(db_path: str = DEFAULT_DB_PATH):
    log = SyncLog(db_path)
    try:
        yield log
    finally:
        log.close()
