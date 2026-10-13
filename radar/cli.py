"""命令行入口。

    python -m radar run            # 完整跑一轮：采集 + 评估 + 出报告
    python -m radar catalog        # 查看已加载的官方认定目录
    python -m radar verify         # 生成人工核对清单（第一阶段验收用）
    python -m radar status         # 查看库内赛事与推送状态
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from .catalog import Catalog
from .config import load_config
from .pipeline import run_pipeline


def _utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def cmd_run(args) -> int:
    cfg = load_config()
    result = run_pipeline(
        cfg,
        offline=args.offline,
        use_search=not args.no_search,
        force=args.force,
        detail_limit=args.detail_limit,
    )
    stats = result["stats"]
    print("\n完成：")
    print(f"  赛事实体 {stats['records']} 个（新发现 {stats['new_records']} 个）")
    for tier in ("重点关注", "潜在机会", "低优先级/证据不足"):
        n = sum(1 for r in result["records"] if r["tier"] == tier)
        print(f"  {tier}: {n}")
    print(f"  周报: {stats['digest']}")
    print(f"  结构化数据: {cfg.candidates_path}")
    return 0


def cmd_catalog(args) -> int:
    cfg = load_config()
    cat = Catalog.load(cfg.catalog_path)
    if not cat.entries:
        print("尚未生成目录数据，请先运行: python tools/import_ynu_catalog.py ...")
        return 1
    print(f"{cat.meta.get('title')}")
    print(f"来源: {cat.meta.get('source_url')}")
    print(f"版本: {cat.meta.get('version')}  条目数: {len(cat.entries)}")
    print(f"类别分布: {cat.categories}")
    print()
    if args.cs:
        rows = [
            e for e in cat.entries
            if e.dept in ("软件学院", "信息学院")
            or any(k in e.name for k in ("计算机", "软件", "程序", "机器人", "智能", "信息", "数据"))
        ]
        print(f"计算机相关条目 {len(rows)} 项：")
        for e in rows:
            print(f"  {e.no:>3} {e.category} {e.name}（{e.dept or '未标注'}）")
    return 0


def cmd_verify(args) -> int:
    """生成人工核对清单：每条记录都给出原始链接与抽取依据，便于逐条打勾。"""
    cfg = load_config()
    if not cfg.candidates_path.exists():
        print("还没有运行过采集，请先执行: python -m radar run")
        return 1
    data = json.loads(cfg.candidates_path.read_text(encoding="utf-8"))
    records = data["records"]

    with_date = [r for r in records if r.get("registration_last")]
    with_cat = [r for r in records if r.get("catalog_category")]
    official = [r for r in records if any(n["authority"] == "official" for n in r["notices"])]

    lines = [
        "# 赛事雷达 · 抽样核对清单",
        "",
        f"- 生成时间：{data['generated_at']}",
        f"- 记录总数：{len(records)}",
        f"- 含报名日期的记录：{len(with_date)}",
        f"- 已匹配官方认定目录的记录：{len(with_cat)}",
        f"- 有官方来源支撑的记录：{len(official)}",
        "",
        "> 核对方法：打开「通知原文」链接，逐条确认下列抽取值是否正确，勾选「一致 / 不一致」。",
        "",
    ]
    for r in records[: args.limit]:
        lines.append(f"## {r['name']}（{r['tier']}）")
        lines.append("")
        lines.append(f"- 通知原文：{r['notices'][0]['url'] if r.get('notices') else '无'}")
        lines.append(f"- 目录匹配：{r.get('catalog_category') or '未收录'}"
                     + (f"（第 {r.get('catalog_no')} 项，匹配方式 {r.get('catalog_match_method')}）"
                        if r.get("catalog_no") else ""))
        lines.append(f"- 抽取到的报名截止：{r.get('registration_last') or '未抽取到'}")
        for ev in (r.get("registration_evidence") or [])[:2]:
            lines.append(f"  - 依据：「{ev.get('evidence', '')[:110]}」")
        lines.append(f"- 主办方：{r.get('organizer_text') or '未抽取到'}")
        lines.append(f"- 费用：{r.get('fee_text') or '未抽取到'}")
        lines.append(f"- 首次发现：{r.get('first_seen')}；最近核验：{r.get('last_verified')}")
        lines.append("")
        lines.append("- [ ] 日期一致  - [ ] 来源有效  - [ ] 分类合理")
        lines.append("")

    out = cfg.outbox_dir / f"verification-{date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"核对清单 -> {out}")
    print(f"  记录 {len(records)} 条，其中 {len(with_date)} 条有日期证据，"
          f"{len(with_cat)} 条匹配到目录")
    return 0


def cmd_status(args) -> int:
    cfg = load_config()
    if not cfg.candidates_path.exists():
        print("尚无运行结果，先运行 python -m radar run")
        return 0
    data = json.loads(cfg.candidates_path.read_text(encoding="utf-8"))
    records = data["records"]
    print(f"最近一次运行时间: {data['generated_at']}")
    print(f"本轮赛事实体: {len(records)}")
    by_tier: dict[str, int] = {}
    for r in records:
        by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
    for k, v in sorted(by_tier.items()):
        print(f"  {k}: {v}")
    with_date = sum(1 for r in records if r.get("registration_last"))
    with_cat = sum(1 for r in records if r.get("catalog_category"))
    print(f"  含报名日期: {with_date}；匹配认定目录: {with_cat}；"
          f"新发现: {data['stats'].get('new_records', 0)}")
    print("\n关注度最高的 10 条：")
    for r in records[:10]:
        print(f"  {r['score_total']:>5}  {r['tier']:<12} {r['name'][:40]}")
    return 0


def cmd_doctor(args) -> int:
    """启用自检：逐项确认工具真的可用。"""
    from .doctor import run_checks, verdict

    cfg = load_config()
    print("计算机赛事雷达 · 启用自检")
    print("=" * 62)
    checks = run_checks(cfg, send_test=args.test_notify)
    marks = {"ok": "[OK]  ", "warn": "[注意]", "fail": "[失败]"}
    for check in checks:
        print(f"{marks.get(check.status, '[?]')} {check.name}：{check.detail}")
    status, message = verdict(checks)
    print("=" * 62)
    print(("全部就绪：" if status == "ok" else "结论：") + message)
    if status == "fail":
        return 2
    return 0


def cmd_notify(args) -> int:
    """检查通知配置、预览待推送内容；--test 会真实发送一条测试消息。"""
    import copy

    from .notify import build_message, dispatch
    from .store import Store

    cfg = load_config()
    notify_cfg = cfg.settings.get("notify", {}) or {}

    if args.redeliver:
        from .notify import dispatch
        from .store import Store

        if not cfg.db_path.exists():
            print("还没有数据库，先运行 python -m radar run")
            return 1
        store = Store(cfg.db_path)
        rows = store.conn.execute(
            "SELECT id FROM push_log ORDER BY id DESC LIMIT ?", (args.redeliver,)
        ).fetchall()
        if not rows:
            print("没有可补发的提醒记录")
            store.close()
            return 0
        ids = [int(r["id"]) for r in rows]
        marks = ",".join("?" for _ in ids)
        store.conn.execute(
            f"UPDATE push_log SET status = 'pending' WHERE id IN ({marks})", ids
        )
        store.conn.commit()
        pending = store.pending_pushes()
        print(f"把最近 {len(ids)} 条提醒重新置为待推送，现在投递一次……")
        result = dispatch(cfg, pending, log=print)
        if result.ok and not result.dry_run:
            store.mark_pushes([int(r["id"]) for r in pending], status="sent")
        elif result.dry_run:
            store.mark_pushes([int(r["id"]) for r in pending], status="dry-run",
                              error=result.detail)
        else:
            store.mark_pushes([int(r["id"]) for r in pending], status="pending",
                              error=result.detail)
        print(f"结果：{'成功' if result.ok else '失败'} —— {result.detail}")
        store.close()
        return 0 if result.ok else 2

    print("== 当前通知配置 ==")
    print(f"  渠道: {notify_cfg.get('channel')}")
    print(f"  已启用: {notify_cfg.get('enabled')}   干跑模式: {notify_cfg.get('dry_run')}")
    for name, key_field in (("wecom", "webhook_env"), ("serverchan", "key_env")):
        env_name = (notify_cfg.get(name) or {}).get(key_field)
        if env_name:
            print(f"  {name} 环境变量 {env_name}: {'已设置' if os.environ.get(env_name) else '未设置'}")
    email_cfg = notify_cfg.get("email") or {}
    if email_cfg.get("host"):
        user_env = email_cfg.get("username_env", "COMPRADAR_SMTP_USER")
        print(f"  邮件 {email_cfg['host']}:{email_cfg.get('port')} "
              f"账号 {user_env}: {'已设置' if os.environ.get(user_env) else '未设置'}")

    rows: list[dict] = []
    if args.test:
        rows = [{
            "push_type": "测试消息",
            "title": "赛事雷达测试消息",
            "body": "如果你收到这条消息，说明通知渠道配置成功。\n"
                    "正式运行时只会推送新赛事、临近截止、日期变更等需要行动的信息。",
        }]
    elif cfg.db_path.exists():
        store = Store(cfg.db_path)
        rows = [dict(row) for row in store.pending_pushes()]
        store.close()

    title, body = build_message(rows)
    print("\n== 将要推送的内容 ==")
    print(f"标题：{title}")
    print(body or "（暂无待推送内容）")

    if args.test:
        if notify_cfg.get("channel", "file") == "file":
            print("\n注意：当前渠道是 file，只会写本地文件，不会发出外部消息。")
            print("要真实测试，请先把 [notify].channel 改成 wecom / serverchan / email，")
            print("并把对应的环境变量配上，然后重新执行本命令。")
            return 0
        test_cfg = copy.deepcopy(cfg)
        test_cfg.settings["notify"] = dict(notify_cfg)
        test_cfg.settings["notify"]["enabled"] = True
        test_cfg.settings["notify"]["dry_run"] = False
        print("\n== 真实发送测试消息 ==")
        result = dispatch(test_cfg, rows, log=print)
        print(f"结果：{'成功' if result.ok else '失败'} —— {result.detail}")
        return 0 if result.ok else 2
    return 0


def cmd_dashboard(args) -> int:
    """只重新生成仪表盘，不重新采集。"""
    from .dashboard import build_payload, write_dashboard
    from .store import Store

    cfg = load_config()
    if not cfg.candidates_path.exists():
        print("还没有运行结果，先执行: python -m radar run")
        return 1
    data = json.loads(cfg.candidates_path.read_text(encoding="utf-8"))

    pushes: list[dict] = []
    if cfg.db_path.exists():
        store = Store(cfg.db_path)
        pushes = [
            {"time": row["created_at"][:19], "type": row["push_type"],
             "title": row["title"], "status": row["status"]}
            for row in store.conn.execute(
                "SELECT * FROM push_log ORDER BY id DESC LIMIT 30"
            ).fetchall()
        ]
        store.close()

    payload = build_payload(
        data["records"], data.get("discovery", []), data.get("stats", {}),
        data.get("catalog", {}), data.get("changes", []), pushes,
        generated_at=data.get("generated_at"),
    )
    path = write_dashboard(cfg, payload)
    print(f"仪表盘 -> {path}")
    print(f"  赛事 {len(payload['records'])} 个，"
          f"重点关注 {payload['tier_counts'].get('重点关注', 0)} 个")
    if args.open:
        import webbrowser

        webbrowser.open(path.as_uri())
        print("  已在默认浏览器中打开")
    return 0


def cmd_db(args) -> int:
    """查看 SQLite 库：总量、最近变化、已推送记录。"""
    cfg = load_config()
    if not cfg.db_path.exists():
        print("还没有数据库，先运行 python -m radar run")
        return 1
    from .store import Store

    store = Store(cfg.db_path)
    summary = store.summary()
    print("== 库内总量 ==")
    print(f"  赛事实体: {summary['competitions']}")
    print(f"  通知原文: {summary['notices']}")
    print(f"  运行次数: {summary['runs']}")
    print(f"  变化记录: {summary['changes']}")
    print(f"  提醒记录: {summary['pushes']}（含历史，便于去重）")
    print(f"  等级分布: {summary['tiers']}")

    print("\n== 最近变化 ==")
    rows = store.recent_changes(args.limit)
    if not rows:
        print("  （暂无变化记录）")
    for row in rows:
        print(f"  {row['detected_at'][:19]}  [{row['change_type']}] {row['competition']}"
              f"  {row['detail']}")

    if args.pushes:
        print("\n== 提醒记录 ==")
        cur = store.conn.execute(
            "SELECT * FROM push_log ORDER BY id DESC LIMIT ?", (args.limit,)
        )
        for row in cur.fetchall():
            print(f"  {row['created_at'][:19]}  [{row['push_type']}] {row['title']}"
                  f"  status={row['status']}")
            if args.body:
                for line in (row["body"] or "").splitlines():
                    print(f"        {line}")

    if args.pending_only:
        print("\n== 待推送 ==")
        for row in store.pending_pushes():
            print(f"  [{row['push_type']}] {row['title']}")
    store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8()
    ap = argparse.ArgumentParser(prog="radar", description="计算机赛事雷达")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="完整跑一轮采集与评估")
    p_run.add_argument("--offline", action="store_true", help="只用本地缓存，不联网")
    p_run.add_argument("--no-search", action="store_true", help="跳过搜索引擎发现通道")
    p_run.add_argument("--force", action="store_true", help="忽略缓存，强制重新抓取")
    p_run.add_argument("--detail-limit", type=int, default=None, help="本轮最多抓取多少条详情页")
    p_run.set_defaults(func=cmd_run)

    p_cat = sub.add_parser("catalog", help="查看官方认定目录")
    p_cat.add_argument("--cs", action="store_true", help="只看计算机相关条目")
    p_cat.set_defaults(func=cmd_catalog)

    p_ver = sub.add_parser("verify", help="生成人工核对清单")
    p_ver.add_argument("--limit", type=int, default=40)
    p_ver.set_defaults(func=cmd_verify)

    p_st = sub.add_parser("status", help="查看库内状态")
    p_st.set_defaults(func=cmd_status)

    p_db = sub.add_parser("db", help="查看 SQLite 库：变化、提醒、总量")
    p_db.add_argument("--limit", type=int, default=20)
    p_db.add_argument("--pushes", action="store_true", help="同时列出提醒记录")
    p_db.add_argument("--body", action="store_true", help="列出提醒正文（配合 --pushes）")
    p_db.add_argument("--pending-only", action="store_true", help="只看待推送")
    p_db.set_defaults(func=cmd_db)

    p_nt = sub.add_parser("notify", help="检查通知配置并预览待推送内容")
    p_nt.add_argument("--test", action="store_true",
                      help="真实发送一条测试消息（会忽略 dry_run 与 enabled 开关）")
    p_nt.add_argument("--redeliver", type=int, metavar="N", default=0,
                      help="把最近 N 条提醒重新投递一次（换渠道后补发用）")
    p_nt.set_defaults(func=cmd_notify)

    p_dash = sub.add_parser("dashboard", help="重新生成网页仪表盘")
    p_dash.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
    p_dash.set_defaults(func=cmd_dashboard)

    p_doc = sub.add_parser("doctor", help="启用自检：逐项确认依赖、目录、规则、数据库、推送、定时任务")
    p_doc.add_argument("--test-notify", action="store_true",
                       help="顺便真实发送一条通知（桌面通知渠道会弹一条）")
    p_doc.set_defaults(func=cmd_doctor)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
