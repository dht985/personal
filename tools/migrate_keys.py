"""把旧的 catalog:<目录序号> 主键迁移成 catalog:<赛事名>。

原因：2026 版目录条目数变了（126 → 111），序号整体位移；继续用序号当主键，
同一场比赛会被当成新赛事，首次发现时间和历次评估都会丢。

用法：python tools/migrate_keys.py [旧目录json]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from radar.config import load_config  # noqa: E402
from radar.store import Store  # noqa: E402
from radar.textutil import squeeze  # noqa: E402


def main() -> int:
    cfg = load_config(ROOT)
    old_catalog_path = Path(sys.argv[1]) if len(sys.argv) > 1 else cfg.catalog_prev_path
    if not old_catalog_path.exists():
        print(f"找不到旧目录文件 {old_catalog_path}")
        return 1
    if not cfg.db_path.exists():
        print("还没有数据库，不需要迁移")
        return 0

    old = json.loads(old_catalog_path.read_text(encoding="utf-8"))
    no_to_name = {e["no"]: e["name"] for e in old["entries"]}

    store = Store(cfg.db_path)
    rows = store.conn.execute("SELECT id, key, name FROM competitions").fetchall()
    moved = skipped = conflicted = 0
    for row in rows:
        key = row["key"]
        if not key.startswith("catalog:"):
            continue
        suffix = key.split(":", 1)[1]
        if not suffix.isdigit():  # 已经是新格式
            continue
        name = no_to_name.get(int(suffix))
        if not name:
            skipped += 1
            continue
        new_key = "catalog:" + squeeze(name)
        exists = store.conn.execute(
            "SELECT id FROM competitions WHERE key = ?", (new_key,)
        ).fetchone()
        if exists and exists["id"] != row["id"]:
            conflicted += 1
            continue
        store.conn.execute(
            "UPDATE competitions SET key = ? WHERE id = ?", (new_key, row["id"])
        )
        moved += 1
    store.conn.commit()

    print(f"迁移完成：改了 {moved} 条，跳过 {skipped} 条，键冲突 {conflicted} 条")
    for row in store.conn.execute(
        "SELECT key, name, first_seen FROM competitions ORDER BY id LIMIT 5"
    ).fetchall():
        print(f"  {row['key'][:44]:<46} 首次发现 {row['first_seen'][:19]}")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
