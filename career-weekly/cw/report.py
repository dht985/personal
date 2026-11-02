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
    flags = []
    if item.get("is_new"):
        flags.append("🆕")
    if item.get("content_changed"):
        flags.append("🔄")
    flag = " ".join(flags) + " " if flags else ""
    lines = [f"- {flag}**{meta}** — {item['title']}（{link}）{tail}"]
    facts = item.get("facts") or {}
    fields = []
    if facts.get("employment_type"):
        fields.append("类型：" + "/".join(facts["employment_type"][:2]))
    if facts.get("education"):
        fields.append("学历：" + "/".join(facts["education"][:2]))
    if facts.get("technical_terms"):
        fields.append("技术词：" + "、".join(facts["technical_terms"][:6]))
    if facts.get("locations"):
        fields.append("地点：" + "、".join(facts["locations"][:2]))
    deadline = facts.get("deadline") or {}
    if deadline.get("date"):
        try:
            remaining = (date.fromisoformat(deadline["date"]) - date.today()).days
            state = f"剩 {remaining} 天" if remaining >= 0 else f"已过 {-remaining} 天"
        except ValueError:
            state = ""
        fields.append(f"截止：{deadline['date']}" + (f"（{state}）" if state else ""))
    elif deadline.get("text"):
        fields.append("截止：" + deadline["text"][:40])
    if facts.get("apply_url"):
        fields.append(f"入口：[申请/报名]({facts['apply_url']})")
    attachments = facts.get("attachments") or []
    if attachments:
        attachment_link = attachments[0]
        fields.append(f"附件：[{attachment_link['title'][:24] or 'PDF'}]({attachment_link['url']})")
    if facts.get("extraction_errors"):
        fields.append("附件：部分未能解析")
    if fields:
        lines.append("  - 关键信息：" + "；".join(fields))
    return "\n".join(lines)


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
        f"其中 {stats.get('sources_with_items', 0)} 个解析到条目，"
        f"{stats.get('empty_sources', 0)} 个为空，"
        f"{stats.get('failed_sources', 0)} 个不可达；"
        f"抓取 {stats.get('raw_items', 0)} 条，{filter_label} {stats.get('triaged', 0)} 条，"
        f"最终收录 {len(items)} 条",
        f"- 本周新增 {stats.get('new_items', 0)} 条（🆕 标注）；"
        f"详情变化 {stats.get('changed_items', 0)} 条（🔄 标注）；"
        f"已截止招聘 {stats.get('expired_excluded', 0)} 条未展示；"
        f"跨源去重 {stats.get('duplicates', 0)} 条；"
        f"详情增强 {stats.get('detail_fetched', 0)}/{stats.get('detail_attempted', 0)} 条",
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

    unhealthy = stats.get("unhealthy_sources") or []
    if unhealthy:
        source_names = {source.get("id"): source.get("name") for source in cfg.sources}
        lines.append("## 信源健康")
        lines.append("")
        for row in unhealthy[:8]:
            name = source_names.get(row.get("source_id"), row.get("source_id", "未知来源"))
            if row.get("consecutive_error"):
                detail = f"连续失败 {row['consecutive_error']} 次"
            else:
                detail = f"连续空结果 {row['consecutive_empty']} 次"
            if row.get("last_error"):
                detail += f"（{str(row['last_error'])[:36]}）"
            lines.append(f"- {name}：{detail}")
        lines.append("")

    lines.append("## 覆盖与局限")
    lines.append("")
    lines.append("- 仅使用公开页面，未访问任何非公开或需登录内容。")
    lines.append("- 结构化字段由规则从正文和 PDF 中抽取；原文未明确写出的字段留空。")
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
