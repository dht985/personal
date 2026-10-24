"""报告生成：周报（Markdown）+ 重点赛事信息卡。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

NOT_FOUND = "未找到可靠来源（需人工补充）"

TIER_ORDER = ["重点关注", "潜在机会", "低优先级/证据不足"]

VERDICT_LABEL = {"sufficient": "充足", "inconclusive": "证据不充分", "insufficient": "不足"}
MENTOR_LABEL = {"required": "需导师", "self": "可自主", "pending": "待确认"}
DIM_LABEL = {"awareness": "知名度", "mentor": "导师资源", "awards": "获奖先例"}


def profile_tags(record: dict) -> str:
    """给表格/卡片用的紧凑标签，例如「充足·可自主」。"""
    profile = record.get("ynu_profile") or {}
    verdict = VERDICT_LABEL.get(profile.get("verdict"), "未评估")
    mentor = MENTOR_LABEL.get(record.get("mentor_dependency"), "未判定")
    return f"{verdict}·{mentor}"


def best_notice(record: dict) -> dict | None:
    """引用哪条通知：优先校内官方，其次官方，最后才是搜索发现。"""
    notices = record.get("notices") or []
    if not notices:
        return None
    for picker in (
        lambda n: n.get("authority") == "official" and "ynu.edu.cn" in (n.get("url") or ""),
        lambda n: n.get("authority") == "official",
    ):
        for n in notices:
            if picker(n):
                return n
    return notices[0]


def _cell(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = text.replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _slug(record: dict) -> str:
    if record.get("catalog_no"):
        base = f"cat{record['catalog_no']}"
    else:
        base = hashlib.sha1(record["key"].encode("utf-8")).hexdigest()[:8]
    name = re.sub(r"[^\w\u4e00-\u9fff]+", "", record.get("name", ""))[:16]
    return f"{base}-{name}" if name else base


def _evidence_lines(items: list[dict], limit: int = 2) -> list[str]:
    out = []
    for ev in items[:limit]:
        snippet = _cell(ev.get("evidence", ""), 90)
        if snippet:
            out.append(f"  - 原文：「{snippet}」")
    return out


def render_card(record: dict, catalog_meta: dict) -> str:
    """重点赛事信息卡：每个字段都要能追溯到原始来源。"""
    lines: list[str] = []
    add = lines.append
    add(f"# {record['name']}")
    add("")
    add(f"- 等级：**{record['tier']}**（{record.get('tier_reason', '')}）")
    cat = record.get("catalog_category")
    if cat:
        add(
            f"- 云南大学认定目录：**{cat}**（《{catalog_meta.get('title', '')}》第 "
            f"{record.get('catalog_no')} 项，承办单位：{record.get('catalog_dept') or '未标注'}）"
        )
        add(f"  - 目录来源：{catalog_meta.get('source_url', '')}")
    else:
        add(f"- 云南大学认定目录：**未收录于 2025 版目录**（需人工确认是否属于认定范围）")
    add(f"- 与计算机专业适配度：{record.get('cs_fit')}")
    add(f"- 有效期状态：{record.get('deadline_detail')}")
    profile = record.get("ynu_profile") or {}
    if profile:
        dims = {d["key"]: d for d in profile.get("dimensions", [])}
        found = "".join(
            ("✓" if dims.get(k, {}).get("status") == "found" else "✗") + DIM_LABEL[k] + " "
            for k in ("awareness", "mentor", "awards")
        )
        add(f"- 云大支撑：**{VERDICT_LABEL.get(profile.get('verdict'), '未评估')}**（{found.strip()}）")
        add(f"- 完成方式：**{MENTOR_LABEL.get(record.get('mentor_dependency'), '未判定')}**"
            f"（赛事难度：{record.get('difficulty', '未判定')}）")
    est = record.get("szcp_estimate")
    if est:
        add(
            f"- 综测加分（按「国家级一等奖 + 团队排名第一」估算）："
            f"**{est['capped']:g} / {est['cap']:g} 分**（{est['formula']}）"
        )
    add("")

    add("## 一、官方信息")
    add(f"- 主办方/层级：{record.get('organizer_text') or NOT_FOUND}")
    add(f"- 参赛对象：{record.get('eligibility_text') or NOT_FOUND}")
    add(f"- 组队要求：{record.get('team_text') or NOT_FOUND}")
    add(f"- 费用：{record.get('fee_text') or NOT_FOUND}")
    add("")

    add("## 二、时间与报名")
    add(f"- 报名时间（抽取值）：{record.get('registration_first') or '—'} ~ "
        f"{record.get('registration_last') or '—'}")
    ev = _evidence_lines(record.get("registration_evidence", []))
    if ev:
        add("- 报名时间原文依据：")
        lines.extend(ev)
    else:
        add(f"- 报名时间原文依据：{NOT_FOUND}")
    if record.get("contest_time_text"):
        add(f"- 竞赛/阶段时间：{record['contest_time_text']}")
    add("")

    add("## 三、官方入口")
    add(f"- 校内通知：{record['notices'][0]['url']}" if record.get("notices") else f"- 校内通知：{NOT_FOUND}")
    links = record.get("official_links") or []
    if links:
        for link in links[:5]:
            add(f"- 相关链接：{link}")
    else:
        add(f"- 赛事官网/报名入口：{NOT_FOUND}")
    add("")

    add("## 四、往届情况与学生评价")
    if record.get("student_reviews"):
        for item in record["student_reviews"]:
            add(f"- {item['text']}（来源：{item['url']}）")
    else:
        add(f"- 学生评价：{NOT_FOUND}。本项目不会为凑材料生成主观评价。")
    add("")

    add("## 五、判断依据（分维度，不得互相替代）")
    for dim in record.get("dimensions", []):
        add(f"- **{dim['label']}**（{dim['status']}，{dim['score']} 分）：{dim['detail']}")
        for ev in dim.get("evidence", [])[:2]:
            if ev.get("quote"):
                add(f"  - 原文：「{_cell(ev['quote'], 110)}」")
            if ev.get("url"):
                add(f"  - 来源：{ev['url']}")
    add("")

    if profile:
        add("## 五之二、云大生态评估")
        for dim in profile.get("dimensions", []):
            mark = "有据" if dim.get("status") == "found" else "未找到"
            add(f"- **{dim['label']}**（{mark}）")
            for ev in dim.get("evidence", [])[:3]:
                line = f"  - {ev.get('title', '')}"
                if ev.get("url"):
                    line += f" {ev['url']}"
                add(line)
                if ev.get("snippet"):
                    add(f"    - 摘录：{_cell(ev['snippet'], 100)}")
        for note in profile.get("notes", []):
            add(f"- 判定说明：{note}")
        add("")
        add("## 五之三、完成方式判断")
        add(f"- 结论：**{MENTOR_LABEL.get(record.get('mentor_dependency'), '未判定')}**，"
            f"难度 **{record.get('difficulty', '未判定')}**")
        for reason in (record.get("requirement") or {}).get("reasons", []):
            add(f"  - {reason}")
        for ev in (record.get("requirement") or {}).get("evidence", [])[:3]:
            add(f"  - 原文（{ev.get('field', '')}）：「{_cell(ev.get('snippet', ''), 100)}」")
        add("")

    add("## 六、推荐理由 / 风险 / 下一步")
    add(f"- 推荐关注理由：{record.get('tier_reason', '')}")
    if record.get("risks"):
        add("- 主要风险：")
        for r in record["risks"]:
            add(f"  - {r}")
    if record.get("next_actions"):
        add("- 下一步行动：")
        for a in record["next_actions"]:
            add(f"  - {a}")
    add("")

    add("## 七、溯源信息")
    add(f"- 首次发现：{record.get('first_seen', '')}")
    add(f"- 最近核验：{record.get('last_verified', '')}")
    add(f"- 信息可信度：{record.get('authority')}")
    for n in record.get("notices", [])[:6]:
        add(f"  - [{n.get('source_name')}] {n.get('title')}（{n.get('published_at') or n.get('list_date') or '日期未知'}）"
            f" {n['url']}")
    return "\n".join(lines) + "\n"


def _summary_table(records: list[dict]) -> list[str]:
    lines = [
        "| 赛事 | 目录类别 | 适配度 | 报名截止 | 状态 | 总分 | 云大·完成方式 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in records:
        lines.append(
            "| {name} | {cat} | {fit} | {dl} | {st} | {score} | {tag} |".format(
                name=_cell(r["name"], 34),
                cat=r.get("catalog_category") or "未收录",
                fit=r.get("cs_fit", ""),
                dl=r.get("registration_last") or "未抽取到",
                st=r.get("deadline_status", ""),
                score=r.get("score_total", ""),
                tag=profile_tags(r),
            )
        )
    return lines


def render_notifications(rows, generated_at: str | None = None) -> str:
    """待推送提醒：只有新赛事、临近截止、重要变化才会出现在这里。"""
    generated_at = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    lines = ["# 赛事雷达 · 待推送提醒", "", f"- 生成时间：{generated_at}"]
    if not rows:
        lines += ["", "本轮没有需要推送的新信息（没有新赛事、临近截止或重要变化）。"]
        return "\n".join(lines) + "\n"
    lines += [
        f"- 共 {len(rows)} 条",
        "",
        "> 只推送新赛事、报名临近截止、日期/规则变化和等级提升；同一件事不会重复提醒。",
        "",
    ]
    for row in rows:
        lines.append(f"## [{row['push_type']}] {row['title']}")
        lines.append("")
        for line in (row["body"] or "").splitlines():
            lines.append(f"- {line}")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_digest(
    records: list[dict],
    discovery: list[dict],
    stats: dict,
    catalog_meta: dict,
    changes: list[dict],
    generated_at: str | None = None,
) -> str:
    generated_at = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    lines: list[str] = []
    add = lines.append
    add(f"# 计算机赛事雷达 · 周报")
    add("")
    add(f"- 生成时间：{generated_at}")
    add(f"- 目标读者：云南大学计算机科学与技术专业本科生")
    add(f"- 认定目录版本：{catalog_meta.get('title', '未加载')}（{catalog_meta.get('count', 0)} 项）")
    add("")

    add("## 本次运行摘要")
    add(f"- 官方栏目通知：抓取 {stats.get('official_notices', 0)} 条，"
        f"其中计算机相关 {stats.get('cs_notices', 0)} 条")
    add(f"- 详情页核验：{stats.get('detail_fetched', 0)} 条")
    engines = stats.get("discovery_engines") or {}
    engine_text = "、".join(f"{k}×{v}" for k, v in engines.items()) or "未使用"
    add(f"- 主动发现检索：{stats.get('discovery_hits', 0)} 条命中，"
        f"保留 {stats.get('discovery_kept', 0)} 条（引擎：{engine_text}）")
    if stats.get("discovery_blocked_queries"):
        add(f"- ⚠️ 本轮有 {stats['discovery_blocked_queries']} 个检索式因引擎受限未完成，"
            f"本轮的「新赛事发现」可能不完整")
    add(f"- 归并后赛事实体：{stats.get('records', 0)} 个")
    add(f"- 其中新发现：{stats.get('new_records', 0)} 个；本次检测到变化：{len(changes)} 处")
    add("")

    for tier in TIER_ORDER:
        group = [r for r in records if r["tier"] == tier]
        group.sort(key=lambda r: (-(r.get("score_total") or 0), r["name"]))
        add(f"## {tier}（{len(group)}）")
        if not group:
            add("")
            add("本轮没有归入该等级的赛事。")
            add("")
            continue
        add("")
        lines.extend(_summary_table(group if tier != "低优先级/证据不足" else group[:20]))
        add("")
        if tier == "低优先级/证据不足":
            add("> 该等级仅列出名称，用于留痕；未逐一生成信息卡。")
            add("")

    focus = [r for r in records if r["tier"] == "重点关注"]
    if focus:
        add("## 重点关注赛事速览")
        add("")
        for r in focus:
            add(f"### {r['name']}")
            add(f"- 目录类别：{r.get('catalog_category') or '未收录'}"
                + (f"（第 {r.get('catalog_no')} 项）" if r.get("catalog_no") else ""))
            add(f"- 等级依据：{r.get('tier_reason', '')}")
            add(f"- 截止状态：{r.get('deadline_detail')}")
            if r.get("registration_evidence"):
                add(f"- 截止时间原文：{_cell(r['registration_evidence'][0].get('evidence', ''), 100)}")
            add(f"- 通知来源：{r['notices'][0]['url'] if r.get('notices') else '无'}")
            add(f"- 风险：{'；'.join(r.get('risks', [])) or '无明显风险项'}")
            add(f"- 下一步：{'；'.join(r.get('next_actions', []))}")
            add(f"- 详情见信息卡：cards/{_slug(r)}.md")
            add("")

    if changes:
        add("## 变化与提醒")
        add("")
        for c in changes:
            add(f"- [{c['type']}] {c['name']}：{c['detail']}")
        add("")

    kept = [d for d in discovery if d.get("kept")]
    if kept:
        add("## 主动发现通道命中的候选（可能包含你还不知道的赛事）")
        add("")
        lines.append("| 标题 | 摘录 | 匹配目录 | 真实链接 |")
        lines.append("| --- | --- | --- | --- |")
        for d in kept[:30]:
            lines.append(
                "| {t} | {s} | {c} | {u} |".format(
                    t=_cell(d["title"], 36),
                    s=_cell(d.get("snippet", ""), 40),
                    c=d.get("catalog_category") or "未收录",
                    u=d.get("real_url", ""),
                )
            )
        add("")

    add("## 核查说明与局限")
    add("")
    add("- 目录认定、综合测评赋分、保研价值是三个不同概念，本报告分维度呈现，不互相替代。")
    add("- 综测赋分维度当前为「未核实」：尚未取得云南大学现行有效的本科生综合素质测评办法原文。")
    add("- 所有日期均来自通知原文抽取，附原文片段；抽取失败时明确标注，未做推测。")
    add("- 学生评价维度只在有可靠公开来源时才呈现，否则写「未找到足够可靠的公开评价」。")
    add(f"- 原始网页快照保存在 data/raw/ 下，可按 URL 哈希复核。")
    return "\n".join(lines) + "\n"
