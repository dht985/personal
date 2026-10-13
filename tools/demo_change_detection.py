"""端到端演示变化监测：用独立的演示库跑两轮，中途模拟学校更新了报名截止日期。

不会动真实数据库和 outbox，全部写在 data/demo/ 下。
"""

import copy
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from radar.config import load_config  # noqa: E402
from radar.pipeline import run_pipeline  # noqa: E402
from radar.store import Store  # noqa: E402

DEMO = ROOT / "data" / "demo"


def demo_config():
    cfg = load_config(ROOT)
    cfg.settings = copy.deepcopy(cfg.settings)
    paths = cfg.settings["paths"]
    paths["db"] = "data/demo/radar.db"
    paths["candidates"] = "data/demo/candidates.json"
    paths["outbox"] = "data/demo/outbox"
    return cfg


def main() -> int:
    if DEMO.exists():
        shutil.rmtree(DEMO)
    cfg = demo_config()

    print("=" * 64)
    print("第 1 轮：建立基线（离线，使用本地缓存）")
    print("=" * 64)
    run_pipeline(cfg, offline=True, use_search=False)

    store = Store(cfg.db_path)
    row = store.conn.execute(
        "SELECT id, name, registration_last FROM competitions "
        "WHERE name LIKE '%软件测试%' LIMIT 1"
    ).fetchone()
    if row is None:
        print("演示库里没有找到目标赛事，跳过")
        return 1
    old_value = row["registration_last"]
    print(f"\n模拟学校把「{row['name']}」的报名截止日期从 {old_value} 改成 2026-11-15")
    store.conn.execute(
        "UPDATE competitions SET registration_last = '2026-11-15' WHERE id = ?", (row["id"],)
    )
    store.conn.commit()
    store.close()

    print()
    print("=" * 64)
    print("第 2 轮：应该在不知道被人为改动过的情况下，把差异检出来")
    print("=" * 64)
    run_pipeline(cfg, offline=True, use_search=False)

    store = Store(cfg.db_path)
    print("\n== 数据库里的变化记录 ==")
    for change in store.recent_changes(10):
        print(f"  [{change['change_type']}] {change['competition']}：{change['detail']}")
    print("\n== 第 2 轮新产生的提醒（已写入 outbox，同一件事不会重复推送）==")
    pushes = store.conn.execute(
        "SELECT * FROM push_log ORDER BY id DESC LIMIT 1"
    ).fetchall()
    for push in pushes:
        print(f"  [{push['push_type']}] {push['title']}")
        for line in (push["body"] or "").splitlines()[:4]:
            print(f"        {line}")
    summary = store.summary()
    print(f"\n汇总：{summary['competitions']} 个赛事 / {summary['notices']} 条通知 / "
          f"{summary['changes']} 处变化 / {summary['pushes']} 条提醒")
    store.close()
    print(f"\n演示数据在 {DEMO}（可整个目录删掉，不影响正式数据）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
