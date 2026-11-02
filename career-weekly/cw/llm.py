from __future__ import annotations

import json
import re
from datetime import date

import requests

THINK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.S)
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
REASON_LABELS = ("技术招聘", "校园招聘", "技术项目", "研发方向", "政策文件", "低价值新闻")

TRIAGE_PROMPT = """你是信息筛选器。读者是云南大学计算机专业本科生，关注能源/军工类央国企的计算机相关就业信息。
下面是一批公开信息标题。请逐条判断是否值得收录进周报。

收录标准：
- 与计算机、软件、数据、AI、算法、嵌入式、网络安全、工业软件等技术岗位相关
- 或明确是校园招聘、技术岗位招聘
不收录：
- 纯党建、巡视、领导调研、会议通稿
- 与计算机就业无关的行政、财务、审计、后勤
- 重复或信息量极低的导航页

不要做深层解读，只判断收录与否。reason 必须严格从以下标签中选一个：
技术招聘、校园招聘、技术项目、研发方向、政策文件、低价值新闻。

条目：
{items}

只输出 JSON：
{{"decisions": [{{"i": 0, "include": true, "reason": "技术招聘"}}, ...]}}
"""


def _reason_label(reason: str, item: dict) -> str:
    reason = str(reason or "").strip()
    if reason in REASON_LABELS:
        return reason
    if "校园" in reason or "校招" in reason:
        return "校园招聘"
    if "招聘" in reason or "岗位" in reason:
        return "技术招聘"
    if "政策" in reason or "制度" in reason or "规划" in reason:
        return "政策文件"
    if "项目" in reason or "科研" in reason or "成果" in reason:
        return "技术项目"
    if "技术" in reason or "研发" in reason or "算法" in reason or "人工智能" in reason:
        return "研发方向"
    return {
        "招聘": "技术招聘",
        "政策": "政策文件",
        "项目": "技术项目",
        "技术": "研发方向",
    }.get(item.get("signal_type", ""), "低价值新闻")


def triage_batch(items: list[dict], settings: dict) -> dict[int, dict]:
    """批量判断哪些条目值得收录。返回 {序号: {include, reason}}。"""
    llm = settings.get("llm", {})
    if not llm.get("enabled", True) or not items:
        return {}
    lines = []
    for idx, item in enumerate(items):
        lines.append(f"{idx}. [{item.get('signal_type','')}] {item['title'][:90]}")
    prompt = TRIAGE_PROMPT.format(items="\n".join(lines))
    try:
        r = requests.post(
            llm["endpoint"],
            json={
                "model": llm["model"],
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "think": False,
                "options": {"temperature": 0.1},
            },
            timeout=llm.get("timeout_seconds", 120),
        )
        r.raise_for_status()
        content = THINK_RE.sub("", r.json().get("message", {}).get("content", "")).strip()
        data = json.loads(content)
        out = {}
        for d in data.get("decisions", []):
            try:
                i = int(d.get("i"))
            except (TypeError, ValueError):
                continue
            reason = _reason_label(d.get("reason", ""), items[i] if 0 <= i < len(items) else {})
            include = bool(d.get("include")) and reason != "低价值新闻"
            out[i] = {"include": include, "reason": reason, "method": "llm"}
        return out
    except Exception:  # noqa: BLE001
        return {}

PROMPT = """你是职业情报编辑。只根据给定的标题与原文节选写摘要，不得添加原文中不存在的数字、时间、机构或结论。

单位：{unit}
层级：L{level}
类型：{signal}
标题：{title}
原文节选：{excerpt}

只输出 JSON：
{{"fact": "不超过40字，只复述标题中的事实", "why": "不超过40字，必须提到具体的技能、岗位或能力方向，不要写空泛的'提供机会'", "action": "若有明确行动窗口则写，否则为空字符串"}}
"""


def _numbers(text: str) -> list[str]:
    return NUM_RE.findall(text or "")


def verify_numbers(fact: str, source: str) -> bool:
    return all(n in source for n in _numbers(fact))


def action_is_stale(action: str, published_at: str | None) -> bool:
    """行动里写到具体日期且已经过期，就不要再提醒。"""
    if not action:
        return False
    m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", action)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = re.search(r"(\d{1,2})月(\d{1,2})日", action)
        if not m:
            return False
        year = int((published_at or "")[:4] or date.today().year)
        y, mo, d = year, int(m.group(1)), int(m.group(2))
    try:
        return date(y, mo, d) < date.today()
    except ValueError:
        return False


def summarize(item: dict, settings: dict) -> dict:
    llm = settings.get("llm", {})
    fallback = {"fact": item["title"], "why": "", "action": "", "llm": False}
    if not llm.get("enabled", True):
        return fallback
    source_text = (item.get("detail") or "") + " " + item["title"]
    prompt = PROMPT.format(
        unit=item.get("unit_path", ""), level=item.get("level", ""),
        signal=item.get("signal_type", ""), title=item["title"],
        excerpt=(item.get("detail") or "（无正文，只能依据标题）")[:1200],
    )
    try:
        r = requests.post(
            llm["endpoint"],
            json={
                "model": llm["model"],
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.2},
            },
            timeout=llm.get("timeout_seconds", 120),
        )
        r.raise_for_status()
        content = r.json().get("message", {}).get("content", "")
        content = THINK_RE.sub("", content).strip()
        data = json.loads(content)
        fact = str(data.get("fact", "")).strip()[:60]
        why = str(data.get("why", "")).strip()[:60]
        action = str(data.get("action", "")).strip()[:60]
        if not fact or not verify_numbers(fact, source_text):
            return fallback
        return {"fact": fact, "why": why, "action": action, "llm": True}
    except Exception:  # noqa: BLE001
        return fallback
