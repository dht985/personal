from __future__ import annotations

import argparse
import sys

from .config import load
from .discover import candidates, render_toml
from .net import Fetcher
from .pipeline import run
from .store import Store


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(prog="career-weekly")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="抓取并生成周报")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--no-detail", action="store_true", help="不抓取详情正文，只用标题")

    sub.add_parser("status", help="查看数据库状态")
    sub.add_parser("discover", help="发现 L3 部门/实验室候选")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        stats = run(
            load(), limit=args.limit, use_llm=not args.no_llm,
            use_detail=not args.no_detail,
        )
        print(f"\n周报：{stats['report']}（{stats['chars']} 字符）")
        print(f"信源 {stats['sources_ok']}/{stats['sources_total']}，条目 {stats['raw_items']}，"
              f"新增 {stats['new_items']}，模型回退 {stats['llm_fallbacks']}")
        print(f"正文抓取：{stats.get('detail_fetched', 0)} 条")
        return 0

    cfg = load()
    if args.cmd == "discover":
        found = candidates(cfg, Fetcher(cfg))
        if not found:
            print("没有发现候选（多数单位首页未公开组织架构）")
            return 0
        out = cfg.base / "config" / "units_suggested.toml"
        out.write_text(render_toml(found), encoding="utf-8")
        print(f"发现 {len(found)} 个 L3 候选 -> {out}")
        for item in found[:15]:
            print(f"  {item['parent_short']} > {item['name']}")
        return 0
    if not cfg.db_path.exists():
        print("还没有数据库，先运行 python -m cw run")
        return 0
    store = Store(cfg.db_path)
    rows = store.conn.execute(
        "SELECT level, signal_type, COUNT(*) AS n FROM items GROUP BY level, signal_type"
    ).fetchall()
    print(f"库内条目：{sum(r['n'] for r in rows)}")
    for r in rows:
        print(f"  L{r['level']} {r['signal_type']}: {r['n']}")
    recent = store.conn.execute(
        "SELECT title, first_seen FROM items ORDER BY id DESC LIMIT 5"
    ).fetchall()
    print("最近入库：")
    for r in recent:
        print(f"  {r['first_seen'][:19]}  {r['title'][:50]}")
    store.conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
