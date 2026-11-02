from __future__ import annotations

import argparse
from datetime import datetime
import os
import sys

from .config import SOURCE_PURPOSES, load, source_purpose
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
    sub.add_parser("health", help="查看信源健康与连续空结果")
    sub.add_parser("changes", help="查看已检测到的正文变化")
    p_due = sub.add_parser("due", help="判断是否超过指定时间未成功运行")
    p_due.add_argument("--max-age-hours", type=float, default=144)
    sub.add_parser("discover", help="发现 L3 部门/实验室候选")
    sub.add_parser("open", help="打开最新一期周报")
    sub.add_parser("coverage", help="查看各单位的数据覆盖（招聘/采购/项目/投资等）")
    p_ds = sub.add_parser("discover-sources", help="巡检官网，持续补招聘/政策/新闻栏目")
    p_ds.add_argument("--limit", type=int, default=4, help="本轮巡检的单位数")
    p_ds.add_argument("--retry-days", type=int, default=30, help="失败候选的复检间隔")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        stats = run(
            load(), limit=args.limit, use_llm=not args.no_llm,
            use_detail=not args.no_detail,
        )
        print(f"\n周报：{stats['report']}（{stats['chars']} 字符）")
        print(f"信源可达 {stats['sources_ok']}/{stats['sources_total']}，"
              f"解析有内容 {stats['sources_with_items']}，"
              f"空结果 {stats['empty_sources']}，条目 {stats['raw_items']}，"
              f"新增 {stats['new_items']}，模型回退 {stats['llm_fallbacks']}")
        print(
            f"详情增强：{stats.get('detail_fetched', 0)}/"
            f"{stats.get('detail_attempted', 0)} 条，"
            f"变化 {stats.get('changed_items', 0)} 条，"
            f"截止招聘隐藏 {stats.get('expired_excluded', 0)} 条"
        )
        return 0

    cfg = load()
    if args.cmd == "due":
        if not cfg.db_path.exists():
            return 20
        store = Store(cfg.db_path)
        row = store.conn.execute(
            """SELECT finished_at FROM runs
               WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        store.conn.close()
        if row is None:
            return 20
        last = datetime.fromisoformat(row["finished_at"])
        current = datetime.now().astimezone()
        if last.tzinfo is None:
            last = last.astimezone()
        age_hours = (current - last).total_seconds() / 3600
        print(f"距上次成功运行 {age_hours:.1f} 小时")
        return 20 if age_hours >= args.max_age_hours else 0
    if args.cmd == "health":
        if not cfg.db_path.exists():
            print("还没有数据库")
            return 0
        store = Store(cfg.db_path)
        rows = store.conn.execute(
            """SELECT * FROM source_health
               ORDER BY consecutive_error DESC, consecutive_empty DESC,
                        last_checked_at DESC"""
        ).fetchall()
        source_names = {source["id"]: source["name"] for source in cfg.sources}
        print(f"信源健康记录：{len(rows)}")
        for row in rows:
            name = source_names.get(row["source_id"], row["source_id"])
            print(
                f"  {name}: {row['last_status']}，条目 {row['last_item_count']}，"
                f"连续空 {row['consecutive_empty']}，连续失败 {row['consecutive_error']}，"
                f"最近成功 {row['last_success_at'] or '无'}"
            )
        store.conn.close()
        return 0
    if args.cmd == "changes":
        if not cfg.db_path.exists():
            print("还没有数据库")
            return 0
        store = Store(cfg.db_path)
        rows = store.conn.execute(
            """SELECT s.captured_at, s.title, i.url, s.previous_hash, s.content_hash
               FROM item_snapshots s JOIN items i ON i.id = s.item_id
               WHERE s.change_kind = 'changed'
               ORDER BY s.id DESC LIMIT 20"""
        ).fetchall()
        print(f"已检测到正文变化：{len(rows)} 条（最多显示 20 条）")
        for row in rows:
            print(f"  {row['captured_at'][:19]}  {row['title'][:60]}")
            print(f"    {row['url']}")
        store.conn.close()
        return 0
    if args.cmd == "discover-sources":
        from .discover_sources import discover, save

        added = discover(cfg, limit=args.limit, retry_days=args.retry_days)
        if added:
            path = save(cfg, added)
            print(f"新增 {len(added)} 个自动信源 -> {path}")
        else:
            print("本轮没有新增可用信源；巡检状态已持久化，下轮会继续其他单位")
        store = Store(cfg.db_path)
        summary = store.discovery_summary()
        store.conn.close()
        print("历次巡检记录：" + "，".join(
            f"{name} {summary.get(name, 0)}" for name in
            ("accepted", "rejected", "no_candidate", "home_error")
        ))
        return 0
    if args.cmd == "open":
        latest = cfg.outbox_dir / "weekly-latest.md"
        if not latest.exists():
            print("还没有周报，先运行 python -m cw run")
            return 1
        print(f"周报：{latest}")
        if os.name == "nt":
            os.startfile(str(latest))  # type: ignore[attr-defined]
        return 0
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
    if args.cmd == "coverage":
        store = Store(cfg.db_path)
        units = cfg.unit_map()
        rows = store.conn.execute(
            "SELECT unit_id, signal_type, COUNT(*) AS n FROM items GROUP BY unit_id, signal_type"
        ).fetchall()
        by_unit: dict[str, dict[str, int]] = {}
        for r in rows:
            by_unit.setdefault(r["unit_id"], {})[r["signal_type"]] = r["n"]
        kinds = ["招聘", "政策", "采购", "项目", "投资", "战略", "技术"]
        active = set(cfg.focus)
        active_data = {k: v for k, v in by_unit.items() if k in active}
        inactive_data = len(by_unit) - len(active_data)
        print(
            f"重点关注单位 {len(active)}，其中有数据 {len(active_data)}；"
            f"未纳入但历史有数据 {inactive_data}"
        )
        source_counts = {
            purpose: sum(
                1 for src in cfg.sources
                if src.get("unit") in active and source_purpose(src) == purpose
            )
            for purpose in SOURCE_PURPOSES
        }
        print(
            f"重点关注单位信源：招聘 {source_counts['recruit']}，"
            f"政策 {source_counts['policy']}，新闻/项目 {source_counts['news']}"
        )
        covered_channels = {
            (src.get("unit"), source_purpose(src)) for src in cfg.sources
        }
        no_policy = [
            u for u in cfg.units
            if u["id"] in active and (u["id"], "policy") not in covered_channels
        ]
        no_recruit = [
            u for u in cfg.units
            if u["id"] in active and (u["id"], "recruit") not in covered_channels
        ]
        print(
            f"通道缺口：政策 {len(no_policy)} 个单位，招聘 {len(no_recruit)} 个单位"
        )
        print("数据覆盖统计：")
        for k in kinds:
            n = sum(1 for v in active_data.values() if k in v)
            print(f"  {k}: {n} 个单位有数据")
        for uid, counts in sorted(active_data.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
            unit = units.get(uid, {})
            detail = " ".join(f"{k}{counts.get(k,0)}" for k in kinds if counts.get(k))
            missing = [k for k in kinds if not counts.get(k)]
            gap = f"｜缺 {'/'.join(missing)}" if missing else ""
            print(f"  L{unit.get('level','?')} {unit.get('short', uid):<12} {detail}{gap}")
        store.conn.close()
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
