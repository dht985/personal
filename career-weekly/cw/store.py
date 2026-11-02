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
    last_seen TEXT NOT NULL,
    content_hash TEXT,
    content_checked_at TEXT,
    content_changed_at TEXT,
    detail_excerpt TEXT,
    facts_json TEXT,
    extractor_version INTEGER
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
CREATE TABLE IF NOT EXISTS item_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    previous_hash TEXT,
    content_hash TEXT NOT NULL,
    title TEXT,
    detail_excerpt TEXT,
    facts_json TEXT,
    change_kind TEXT,
    captured_at TEXT NOT NULL,
    FOREIGN KEY(item_id) REFERENCES items(id)
);
CREATE INDEX IF NOT EXISTS idx_item_snapshots_item
ON item_snapshots(item_id, captured_at);
CREATE TABLE IF NOT EXISTS source_health (
    source_id TEXT PRIMARY KEY,
    last_checked_at TEXT NOT NULL,
    last_success_at TEXT,
    last_item_count INTEGER NOT NULL DEFAULT 0,
    consecutive_empty INTEGER NOT NULL DEFAULT 0,
    consecutive_error INTEGER NOT NULL DEFAULT 0,
    last_status TEXT NOT NULL,
    last_error TEXT
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
        self._migrate()
        self.conn.commit()
        self.run_id = None

    def _migrate(self) -> None:
        """为旧数据库补列；只做增量迁移，不删除历史数据。"""
        columns = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(items)").fetchall()
        }
        additions = {
            "content_hash": "TEXT",
            "content_checked_at": "TEXT",
            "content_changed_at": "TEXT",
            "detail_excerpt": "TEXT",
            "facts_json": "TEXT",
            "extractor_version": "INTEGER",
        }
        for name, kind in additions.items():
            if name not in columns:
                self.conn.execute(f"ALTER TABLE items ADD COLUMN {name} {kind}")
        snapshot_columns = {
            row["name"] for row in self.conn.execute(
                "PRAGMA table_info(item_snapshots)"
            ).fetchall()
        }
        if "change_kind" not in snapshot_columns:
            self.conn.execute("ALTER TABLE item_snapshots ADD COLUMN change_kind TEXT")

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

    def update_content(
        self, url: str, content_hash: str, detail_excerpt: str, facts: dict,
        extractor_version: int = 1,
    ) -> dict:
        """保存正文快照；返回是否首次建立快照或检测到内容变化。"""
        row = self.conn.execute(
            """SELECT id, title, content_hash, extractor_version
               FROM items WHERE url = ?""",
            (url,),
        ).fetchone()
        if row is None:
            return {"saved": False, "changed": False, "baseline": False}
        previous = row["content_hash"]
        previous_version = row["extractor_version"]
        baseline = previous is None or previous_version != extractor_version
        changed = bool(previous and previous != content_hash and not baseline)
        checked = now()
        facts_json = json.dumps(facts, ensure_ascii=False, sort_keys=True)
        self.conn.execute(
            """UPDATE items SET content_hash = ?, content_checked_at = ?,
               content_changed_at = CASE WHEN ? THEN ? ELSE content_changed_at END,
               detail_excerpt = ?, facts_json = ?, extractor_version = ? WHERE id = ?""",
            (
                content_hash, checked, int(changed), checked,
                detail_excerpt, facts_json, extractor_version, row["id"],
            ),
        )
        if baseline or changed:
            self.conn.execute(
                """INSERT INTO item_snapshots
                   (item_id, previous_hash, content_hash, title, detail_excerpt,
                    facts_json, change_kind, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"], previous, content_hash, row["title"],
                    detail_excerpt, facts_json, "baseline" if baseline else "changed",
                    checked,
                ),
            )
        self.conn.commit()
        return {
            "saved": True,
            "changed": changed,
            "baseline": baseline,
        }

    def record_source_health(
        self, source_id: str, status: str, item_count: int, error: str = "",
    ) -> None:
        """记录可达、空结果和失败状态，HTTP 200 不等于解析成功。"""
        checked = now()
        row = self.conn.execute(
            "SELECT * FROM source_health WHERE source_id = ?", (source_id,),
        ).fetchone()
        previous_empty = int(row["consecutive_empty"]) if row else 0
        previous_error = int(row["consecutive_error"]) if row else 0
        previous_success = row["last_success_at"] if row else None
        if status == "ok" and item_count > 0:
            empty, errors, success = 0, 0, checked
        elif status == "error":
            empty, errors, success = previous_empty, previous_error + 1, previous_success
        else:
            empty, errors, success = previous_empty + 1, 0, previous_success
        self.conn.execute(
            """INSERT INTO source_health
               (source_id, last_checked_at, last_success_at, last_item_count,
                consecutive_empty, consecutive_error, last_status, last_error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_id) DO UPDATE SET
                 last_checked_at = excluded.last_checked_at,
                 last_success_at = excluded.last_success_at,
                 last_item_count = excluded.last_item_count,
                 consecutive_empty = excluded.consecutive_empty,
                 consecutive_error = excluded.consecutive_error,
                 last_status = excluded.last_status,
                 last_error = excluded.last_error""",
            (
                source_id, checked, success, item_count, empty, errors,
                status, error or None,
            ),
        )
        self.conn.commit()

    def unhealthy_sources(self, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            """SELECT * FROM source_health
               WHERE consecutive_empty >= 2 OR consecutive_error >= 1
               ORDER BY consecutive_error DESC, consecutive_empty DESC,
                        last_checked_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
