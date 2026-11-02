from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime

PRIORITY = {
    "招聘": 0, "政策": 1, "采购": 2, "项目": 3,
    "投资": 4, "战略": 5, "技术": 6,
}
LEVEL_NAME = {1: "L1 集团总部", 2: "L2 院所/子公司", 3: "L3 下属部门"}
PURPOSE_NAME = {"recruit": "招聘", "policy": "政策", "news": "新闻/项目"}


def sort_key(item: dict):
    return (
        0 if item.get("is_new") else 1,
        PRIORITY.get(item.get("signal_type"), 9),
        "0" if item.get("published_at") else "1",
        item.get("published_at") or "",
        item["title"],
    )


def _line(item: dict, cfg) -> str:
    triage = item.get("triage") or {}
    reason = triage.get("reason") or ""
    tag = f"[L{item['level']}]"
    purpose = PURPOSE_NAME.get(item.get("source_purpose"), item.get("source_purpose", ""))
    meta = (
        f"{tag} {item.get('unit_path','')} · "
        f"{item.get('signal_type','')}{f' · {purpose}源' if purpose else ''}"
    )
    src = item.get("source_name", "")
    when = f"，{item['published_at']}" if item.get("published_at") else ""
    link = f"[{src}]({item['url']}){when}"
    label = "规则理由" if triage.get("method") == "rules" else "筛选理由"
    tail = f"　{label}：{reason}" if reason else ""
    flag = "🆕 " if item.get("is_new") else ""
    return f"- {flag}**{meta}** — {item['title']}（{link}）{tail}"


def render(items: list[dict], cfg, stats: dict) -> str:
    today = date.today()
    purposes = stats.get("source_purposes", {})
    signal_counts = Counter(i.get("signal_type") for i in items)
    filter_label = "AI 筛选" if stats.get("filter_mode") == "llm" else "规则筛选"
    lines = [
        f"# 职业情报周报 · {today.isoformat()}（第 {today.isocalendar().week} 周）",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 覆盖：{stats.get('sources_ok', 0)}/{stats.get('sources_total', 0)} 个信源；"
        f"抓取 {stats.get('raw_items', 0)} 条，{filter_label} {stats.get('triaged', 0)} 条，"
        f"最终收录 {len(items)} 条",
        f"- 本周新增 {stats.get('new_items', 0)} 条（🆕 标注）；"
        f"跨源去重 {stats.get('duplicates', 0)} 条；"
        f"未能生成：{stats.get('failed_sources', 0)} 个源",
        f"- 本期收录信号：招聘 {signal_counts.get('招聘', 0)} 条，"
        f"政策 {signal_counts.get('政策', 0)} 条；"
        f"启用招聘源 {purposes.get('recruit', 0)} 个，"
        f"政策源 {purposes.get('policy', 0)} 个，"
        f"新闻/项目源 {purposes.get('news', 0)} 个",
        "",
    ]

    ordered = sorted(items, key=lambda x: x.get("published_at") or "", reverse=True)
    ordered.sort(
        key=lambda x: (
            PRIORITY.get(x.get("signal_type"), 9),
            0 if x.get("is_new") else 1,
        )
    )
    by_level: dict[int, list[dict]] = {}
    for item in ordered:
        by_level.setdefault(item["level"], []).append(item)

    for level in (1, 2, 3):
        group = by_level.get(level) or []
        lines.append(f"## {LEVEL_NAME[level]}（{len(group)}）")
        lines.append("")
        if not group:
            lines.append("本周无变化。")
            lines.append("")
            continue
        for item in group:
            lines.append(_line(item, cfg))
        lines.append("")

    counts = Counter()
    for item in items:
        for tid in item.get("tracks", []):
            counts[tid] += 1
    names = {t["id"]: t["name"] for t in cfg.tracks}
    if counts:
        lines.append("## 赛道信号")
        lines.append("")
        for tid, n in counts.most_common():
            lines.append(f"- {names.get(tid, tid)}：{n} 条")
        lines.append("")

    lines.append("## 覆盖与局限")
    lines.append("")
    lines.append("- 仅使用公开页面，未访问任何非公开或需登录内容。")
    if stats.get("triage_fallback_batches"):
        lines.append(f"- {stats['triage_fallback_batches']} 批筛选未返回结果，已按规则命中先收录。")
    for name in stats.get("failed_sources_list", []):
        lines.append(f"- 抓取失败：{name}")
    if stats.get("filter_mode") == "llm":
        lines.append("- 正文只保留原标题，未做改写；收录理由由 AI 判断，仅供筛选参考。")
    else:
        lines.append("- 正文只保留原标题，未做改写；本轮未调用大模型，按关键词规则筛选。")
    lines.append("")
    return "\n".join(lines)
