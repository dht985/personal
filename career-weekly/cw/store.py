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
        self.conn.execute("UPDATE items SET last_seen = ? WHERE id = ?", (now(), row["id"]))
        self.conn.commit()
        return False
