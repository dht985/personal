from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    source_id TEXT,
    unit_id TEXT,
    level INTEGER,
    title TEXT,
    signal_type TEXT,
    published_at TEXT,
    tracks TEXT,
    tags TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    stats_json TEXT
);
CREATE TABLE IF NOT EXISTS discovery_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    query TEXT NOT NULL,
    candidate_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    detail TEXT,
    checked_at TEXT NOT NULL,
    UNIQUE(unit_id, purpose, query, candidate_url)
);
CREATE INDEX IF NOT EXISTS idx_discovery_lookup
ON discovery_attempts(unit_id, purpose, candidate_url, checked_at);
"""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.run_id = None

    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (now(),))
        self.conn.commit()
        self.run_id = int(cur.lastrowid)
        return self.run_id

    def finish_run(self, stats: dict) -> None:
        if self.run_id is None:
            return
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, stats_json = ? WHERE id = ?",
            (now(), json.dumps(stats, ensure_ascii=False), self.run_id),
        )
        self.conn.commit()

    def upsert(self, item: dict) -> bool:
        row = self.conn.execute("SELECT id FROM items WHERE url = ?", (item["url"],)).fetchone()
        if row is None:
            self.conn.execute(
                """INSERT INTO items
                   (url, source_id, unit_id, level, title, signal_type, published_at,
                    tracks, tags, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["url"], item["source_id"], item["unit_id"], item["level"],
                    item["title"], item["signal_type"], item.get("published_at"),
                    json.dumps(item.get("tracks", []), ensure_ascii=False),
                    json.dumps(item.get("tags", []), ensure_ascii=False), now(), now(),
                ),
            )
            self.conn.commit()
            return True
        self.conn.execute(
            """UPDATE items SET source_id = ?, unit_id = ?, level = ?, title = ?,
               signal_type = ?, published_at = ?, tracks = ?, tags = ?, last_seen = ?
               WHERE id = ?""",
            (
                item["source_id"], item["unit_id"], item["level"], item["title"],
                item["signal_type"], item.get("published_at"),
                json.dumps(item.get("tracks", []), ensure_ascii=False),
                json.dumps(item.get("tags", []), ensure_ascii=False),
                now(), row["id"],
            ),
        )
        self.conn.commit()
        return False

    def discovery_checked_at(
        self, unit_id: str, purpose: str, candidate_url: str,
    ) -> str | None:
        row = self.conn.execute(
            """SELECT checked_at FROM discovery_attempts
               WHERE unit_id = ? AND purpose = ? AND candidate_url = ?
               ORDER BY checked_at DESC LIMIT 1""",
            (unit_id, purpose, candidate_url),
        ).fetchone()
        return row["checked_at"] if row else None

    def record_discovery(
        self, unit_id: str, purpose: str, query: str, candidate_url: str,
        status: str, detail: str = "",
    ) -> None:
        checked = now()
        self.conn.execute(
            """INSERT INTO discovery_attempts
               (unit_id, purpose, query, candidate_url, status, detail, checked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(unit_id, purpose, query, candidate_url)
               DO UPDATE SET status = excluded.status, detail = excluded.detail,
                             checked_at = excluded.checked_at""",
            (unit_id, purpose, query, candidate_url, status, detail, checked),
        )
        self.conn.commit()

    def discovery_summary(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM discovery_attempts GROUP BY status"
        ).fetchall()
        return {r["status"]: r["n"] for r in rows}
