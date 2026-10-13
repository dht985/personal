"""SQLite 持久化：赛事、通知、证据、评估、变化、推送记录。

设计要点：
- competitions 是赛事实体，key 跨批次稳定（catalog:<序号> 或 name:<规范化名>）。
- notices 是通知原文，按规范化 URL 唯一，保留首次发现与最近出现时间。
- changes 记录每一处变化；push_log 记录已推送内容，用于"同一件事不重复提醒"。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    stats_json    TEXT
);

CREATE TABLE IF NOT EXISTS competitions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    key                TEXT NOT NULL UNIQUE,
    name               TEXT NOT NULL,
    catalog_no         INTEGER,
    catalog_category   TEXT,
    catalog_dept       TEXT,
    match_method       TEXT,
    match_score        REAL,
    tier               TEXT,
    score_total        REAL,
    cs_fit             TEXT,
    deadline_status    TEXT,
    registration_first TEXT,
    registration_last  TEXT,
    fee_text           TEXT,
    team_text          TEXT,
    eligibility_text   TEXT,
    organizer_text     TEXT,
    contest_time_text  TEXT,
    authority          TEXT,
    first_seen         TEXT NOT NULL,
    last_verified      TEXT NOT NULL,
    last_changed       TEXT
);

CREATE TABLE IF NOT EXISTS notices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,
    url_key       TEXT NOT NULL UNIQUE,
    source_id     TEXT,
    source_name   TEXT,
    authority     TEXT,
    title         TEXT,
    published_at  TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS competition_notices (
    competition_id INTEGER NOT NULL,
    notice_id      INTEGER NOT NULL,
    role           TEXT DEFAULT 'notice',
    PRIMARY KEY (competition_id, notice_id, role)
);

CREATE TABLE IF NOT EXISTS valuations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    competition_id INTEGER NOT NULL,
    dimension      TEXT NOT NULL,
    status         TEXT,
    score          REAL,
    detail         TEXT,
    checked_at     TEXT NOT NULL,
    run_id         INTEGER,
    UNIQUE (competition_id, dimension, checked_at)
);

CREATE TABLE IF NOT EXISTS changes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    competition_id INTEGER,
    competition    TEXT,
    change_type    TEXT NOT NULL,
    field          TEXT,
    old_value      TEXT,
    new_value      TEXT,
    detail         TEXT,
    detected_at    TEXT NOT NULL,
    run_id         INTEGER
);

CREATE TABLE IF NOT EXISTS push_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    push_key       TEXT NOT NULL UNIQUE,
    competition_id INTEGER,
    competition    TEXT,
    push_type      TEXT NOT NULL,
    title          TEXT,
    body           TEXT,
    created_at     TEXT NOT NULL,
    sent_at        TEXT,
    channel        TEXT,
    status         TEXT DEFAULT 'pending',
    attempts       INTEGER DEFAULT 0,
    last_error     TEXT
);

CREATE INDEX IF NOT EXISTS idx_changes_time ON changes(detected_at);
CREATE INDEX IF NOT EXISTS idx_valuations_comp ON valuations(competition_id);
"""

TRACKED_FIELDS = [
    "name",
    "catalog_category",
    "tier",
    "registration_first",
    "registration_last",
    "fee_text",
    "team_text",
    "eligibility_text",
    "organizer_text",
    "contest_time_text",
]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Change:
    competition: str
    change_type: str
    field: str
    old_value: str | None
    new_value: str | None
    detail: str
    competition_id: int | None = None


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()
        self.run_id: int | None = None

    def _migrate(self) -> None:
        """给既有库补列，避免因为加了字段就要重建数据库。"""
        existing = {
            row["name"] for row in self.conn.execute("PRAGMA table_info(push_log)")
        }
        for column, ddl in (
            ("attempts", "ALTER TABLE push_log ADD COLUMN attempts INTEGER DEFAULT 0"),
            ("last_error", "ALTER TABLE push_log ADD COLUMN last_error TEXT"),
        ):
            if column not in existing:
                self.conn.execute(ddl)

    # ---- run lifecycle ------------------------------------------------
    def start_run(self) -> int:
        cur = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (_now(),))
        self.conn.commit()
        self.run_id = int(cur.lastrowid)
        return self.run_id

    def finish_run(self, stats: dict) -> None:
        if self.run_id is None:
            return
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, stats_json = ? WHERE id = ?",
            (_now(), json.dumps(stats, ensure_ascii=False), self.run_id),
        )
        self.conn.commit()

    # ---- lookups ------------------------------------------------------
    def get_competition(self, key: str) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM competitions WHERE key = ?", (key,))
        return cur.fetchone()

    def notice_years(self, competition_id: int) -> set[str]:
        cur = self.conn.execute(
            """SELECT n.published_at FROM notices n
               JOIN competition_notices cn ON cn.notice_id = n.id
               WHERE cn.competition_id = ? AND n.published_at IS NOT NULL""",
            (competition_id,),
        )
        return {row["published_at"][:4] for row in cur.fetchall() if row["published_at"]}

    def existing_notice_keys(self, competition_id: int) -> set[str]:
        cur = self.conn.execute(
            """SELECT n.url_key FROM notices n
               JOIN competition_notices cn ON cn.notice_id = n.id
               WHERE cn.competition_id = ?""",
            (competition_id,),
        )
        return {row["url_key"] for row in cur.fetchall()}

    def pushed(self, push_key: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM push_log WHERE push_key = ?", (push_key,))
        return cur.fetchone() is not None

    # ---- writes -------------------------------------------------------
    def upsert_competition(self, rec: dict, *, first_seen: str, last_verified: str) -> int:
        row = self.get_competition(rec["key"])
        values = {
            "key": rec["key"],
            "name": rec.get("name"),
            "catalog_no": rec.get("catalog_no"),
            "catalog_category": rec.get("catalog_category"),
            "catalog_dept": rec.get("catalog_dept"),
            "match_method": rec.get("catalog_match_method"),
            "match_score": rec.get("catalog_match_score"),
            "tier": rec.get("tier"),
            "score_total": rec.get("score_total"),
            "cs_fit": rec.get("cs_fit"),
            "deadline_status": rec.get("deadline_status"),
            "registration_first": rec.get("registration_first"),
            "registration_last": rec.get("registration_last"),
            "fee_text": rec.get("fee_text"),
            "team_text": rec.get("team_text"),
            "eligibility_text": rec.get("eligibility_text"),
            "organizer_text": rec.get("organizer_text"),
            "contest_time_text": rec.get("contest_time_text"),
            "authority": rec.get("authority"),
            "first_seen": first_seen,
            "last_verified": last_verified,
            "last_changed": rec.get("last_changed"),
        }
        if row is None:
            cols = ", ".join(values)
            marks = ", ".join("?" for _ in values)
            cur = self.conn.execute(
                f"INSERT INTO competitions ({cols}) VALUES ({marks})", tuple(values.values())
            )
            self.conn.commit()
            return int(cur.lastrowid)
        assignments = ", ".join(f"{c} = ?" for c in values if c != "key")
        params = [v for c, v in values.items() if c != "key"] + [rec["key"]]
        self.conn.execute(f"UPDATE competitions SET {assignments} WHERE key = ?", params)
        self.conn.commit()
        return int(row["id"])

    def upsert_notice(self, notice: dict) -> int:
        from .textutil import canonical_url

        key = canonical_url(notice["url"])
        row = self.conn.execute("SELECT * FROM notices WHERE url_key = ?", (key,)).fetchone()
        if row is None:
            cur = self.conn.execute(
                """INSERT INTO notices (url, url_key, source_id, source_name, authority, title,
                                        published_at, first_seen, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    notice["url"], key, notice.get("source_id"), notice.get("source_name"),
                    notice.get("authority"), notice.get("title"), notice.get("published_at"),
                    _now(), _now(),
                ),
            )
            self.conn.commit()
            return int(cur.lastrowid)
        self.conn.execute(
            "UPDATE notices SET last_seen = ?, title = COALESCE(?, title) WHERE id = ?",
            (_now(), notice.get("title"), row["id"]),
        )
        self.conn.commit()
        return int(row["id"])

    def link(self, competition_id: int, notice_id: int, role: str = "notice") -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO competition_notices (competition_id, notice_id, role)
               VALUES (?, ?, ?)""",
            (competition_id, notice_id, role),
        )
        self.conn.commit()

    def add_valuation(self, competition_id: int, dimension: dict) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO valuations
               (competition_id, dimension, status, score, detail, checked_at, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                competition_id, dimension["key"], dimension["status"], dimension["score"],
                dimension["detail"], _now(), self.run_id,
            ),
        )
        self.conn.commit()

    def add_change(self, change: Change) -> None:
        self.conn.execute(
            """INSERT INTO changes (competition_id, competition, change_type, field,
                                    old_value, new_value, detail, detected_at, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                change.competition_id, change.competition, change.change_type, change.field,
                change.old_value, change.new_value, change.detail, _now(), self.run_id,
            ),
        )
        self.conn.commit()

    def queue_push(
        self, push_key: str, competition_id: int | None, competition: str,
        push_type: str, title: str, body: str, channel: str = "file",
    ) -> bool:
        """已推送过就跳过，保证同一件事不会重复提醒。"""
        if self.pushed(push_key):
            return False
        self.conn.execute(
            """INSERT OR IGNORE INTO push_log
               (push_key, competition_id, competition, push_type, title, body, created_at, channel)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (push_key, competition_id, competition, push_type, title, body, _now(), channel),
        )
        self.conn.commit()
        return True

    # ---- reporting ----------------------------------------------------
    def recent_changes(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM changes ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def pending_pushes(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM push_log WHERE status = 'pending' ORDER BY id"
        ).fetchall()

    def mark_pushes(
        self, ids: list[int], status: str = "sent", error: str | None = None
    ) -> None:
        """更新投递结果。status: sent（已投递）/ dry-run（仅渲染）/ pending（失败待重试）。"""
        if not ids:
            return
        marks = ",".join("?" for _ in ids)
        self.conn.execute(
            f"""UPDATE push_log
                SET status = ?,
                    sent_at = CASE WHEN ? = 'sent' THEN ? ELSE sent_at END,
                    attempts = COALESCE(attempts, 0) + 1,
                    last_error = ?
                WHERE id IN ({marks})""",
            [status, status, _now(), error, *ids],
        )
        self.conn.commit()

    def summary(self) -> dict:
        def count(sql: str) -> int:
            return int(self.conn.execute(sql).fetchone()[0])

        tiers = {
            row["tier"] or "未分层": row["n"]
            for row in self.conn.execute(
                "SELECT tier, COUNT(*) AS n FROM competitions GROUP BY tier"
            ).fetchall()
        }
        return {
            "competitions": count("SELECT COUNT(*) FROM competitions"),
            "notices": count("SELECT COUNT(*) FROM notices"),
            "changes": count("SELECT COUNT(*) FROM changes"),
            "pushes": count("SELECT COUNT(*) FROM push_log"),
            "runs": count("SELECT COUNT(*) FROM runs"),
            "tiers": tiers,
        }

    def close(self) -> None:
        self.conn.close()
