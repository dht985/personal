"""规则抽取：从通知标题与正文中抽取可溯源的字段（日期、费用、组队、主办等）。

设计原则：每一个抽取结果都携带原文片段，抽不到就返回空，不做推测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date

from .textutil import find_dates, guess_publish_year, snippet_around, squeeze


@dataclass
class Evidence:
    field: str
    value: str
    evidence: str
    method: str
    role: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# 赛事名称推断
# --------------------------------------------------------------------------
_LEAD_NOISE = [
    r"^关于(?:转发|组织参加|组织举办|组织开展|组织|举办|开展|做好|参加|印发|公布)?",
    r"^(?:转发|关于)",
    r"^(?:报名参加|报名参赛|报名|参赛|参加)",
    r"^(?:云南大学|云大|我校|昆明理工.{0,4})",
    r"^(?:教务处|本科生院|软件学院|信息学院)[^，,]{0,6}(?:关于)?",
]
_EVENT_NOISE = [
    r"^第[一二三四五六七八九十百零\d]+届",
    r"^(?:20\d{2}年?)",
]
_TAIL_NOISE = [
    r"(?:的)?(?:通知|公告|公示|函|决定|意见|方案|说明|预告)(?:[（(].{0,20}[)）])?$",
    r"[（(](?:第[一二三四五六七八九十\d]+轮|第二轮|初赛|复赛|决赛)[)）]$",
    r"(?:正式启动|开始报名|报名启动)$",
]


def guess_competition_name(title: str) -> str:
    """从通知标题里粗提赛事名，供与官方目录做匹配。"""
    if not title:
        return ""
    t = squeeze(title)
    t = re.sub(r"^【[^】]{0,20}】", "", t)
    for _ in range(3):
        before = t
        for pat in _LEAD_NOISE:
            t = re.sub(pat, "", t)
        if t == before:
            break
    t = re.sub(r"^[《“\"]+", "", t)
    for pat in _EVENT_NOISE:
        t = re.sub(pat, "", t)
    for pat in _TAIL_NOISE:
        t = re.sub(pat, "", t)
    t = re.sub(r"^(20\d{2})年?", "", t)
    t = re.sub(r"[（(][^）)]{0,10}(?:云南大学|云大)[^）)]{0,10}[)）]", "", t)
    t = t.strip(" -—_·。、")
    return t


# --------------------------------------------------------------------------
# 通用字段抽取
# --------------------------------------------------------------------------
def _collect(
    text: str,
    patterns: list[tuple[str, str]],
    field: str,
    *,
    base_year: int | None,
    limit: int = 3,
    require_date: bool = False,
) -> list[Evidence]:
    """按序应用正则；命中后取捕获区间内的日期或原文。"""
    out: list[Evidence] = []
    used: list[tuple[int, int]] = []
    for name, pat in patterns:
        for m in re.finditer(pat, text):
            if any(s <= m.start() < e for s, e in used):
                continue
            span = m.groupdict().get("seg") or m.group(0)
            seg_start = m.start("seg") if "seg" in m.groupdict() else m.start()
            dates = find_dates(span, base_year)
            if dates:
                for d in dates:
                    out.append(
                        Evidence(
                            field=field,
                            value=d["value"],
                            evidence=snippet_around(text, seg_start, seg_start + len(span)),
                            method=f"regex:{name}",
                        )
                    )
            elif not require_date:
                value = squeeze(span)[:60]
                if value:
                    out.append(
                        Evidence(
                            field=field,
                            value=value,
                            evidence=snippet_around(text, seg_start, seg_start + len(span)),
                            method=f"regex:{name}",
                        )
                    )
            used.append((m.start(), m.end()))
            if len(out) >= limit:
                return out
    return out


REGISTRATION_PATTERNS = [
    (
        "reg_deadline",
        r"(?:报名|网上报名|预报名)"
        r"(?:(?!初赛|复赛|决赛|作品|提交|入围|名单|答辩|颁奖)[^。；;]){0,50}?"
        r"(?:截止|截至)(?:时间|日期)?[^。；;]{0,4}?[:：为]?\s*"
        r"(?P<seg>[^。；;\n]{0,45})",
    ),
    (
        "reg_window",
        r"(?:报名|参赛报名)(?:时间|日期|期限)[^。；;]{0,4}?[:：为]\s*"
        r"(?P<seg>(?:(?!初赛|复赛|决赛|作品|提交|入围|名单|答辩|颁奖)[^。；;\n]){0,45})",
    ),
    (
        "reg_colon",
        r"报名[^。；;\n]{0,15}?[:：]\s*"
        r"(?P<seg>(?:(?!初赛|复赛|决赛|作品|提交|入围|名单|答辩|颁奖)[^。；;\n]){0,45})",
    ),
    ("reg_from_now", r"即日起至(?P<seg>[^。；;\n]{0,40})"),
    ("reg_before", r"(?:于|在)(?P<seg>[^。；;\n]{0,30}?)前[^。；;\n]{0,10}?(?:报名|注册|完成报名)"),
    ("reg_deadline2", r"报名截止日期(?:为|是)?[:：]?\s*(?P<seg>[^。；;\n]{0,40})"),
]

CONTEST_TIME_PATTERNS = [
    ("contest_hold", r"(?:拟)?(?:于|在)\s*(?P<seg>[^。；;\n]{0,30}?)(?:举行|举办|进行)"),
    ("stage_time", r"(?P<seg>(?:校赛|校内选拔赛|省级|省赛|国赛|全国总决赛|决赛)[^。；;\n]{0,20}?)(?:时间|安排)[^。；;]{0,4}?[:：为]\s*(?P<seg2>[^。；;\n]{0,40})"),
    ("stage_date", r"(?P<seg>(?:第[一二三四五六七八九十\d]+场|初赛|复赛|决赛|校赛|省赛|国赛|全国总决赛|比赛|竞赛)[^。；;，,\n]{0,36})"),
]

STAGE_CONTEXT_RE = re.compile(
    r"比赛|竞赛|初赛|复赛|决赛|签到|热身|开幕|闭幕|颁奖|省赛|国赛|校赛|总决赛|举行|举办"
)

SUBMISSION_PATTERNS = [
    (
        "submit_deadline",
        r"(?:作品|材料|成果|参赛作品)[^。；;]{0,8}?(?:提交|报送|上传)"
        r"[^。；;]{0,8}?(?:截止|截至)(?:时间|日期)?[^。；;]{0,4}?[:：为]?\s*"
        r"(?P<seg>(?:(?!决赛|公布|答辩|颁奖|入围)[^。；;\n]){0,50})",
    ),
]

AWARD_RATIO_TOTAL_RE = re.compile(
    r"(?:(?:总)?获奖(?:比例|率|名额比例)|(?:总计|合计))"
    r"[^。；;\n]{0,15}?"
    r"(?P<pct>\d{1,3}(?:\.\d+)?)\s*%"
)
AWARD_LEVEL_RE = re.compile(r"一等奖|二等奖|三等奖|金奖|银奖|铜奖")
PERCENT_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%")

FEE_PATTERNS = [
    ("fee_negative", r"(?P<seg>(?:不收取|无需|免收)[^。；;\n]{0,10}(?:报名费|参赛费|费用)|免费(?:报名|参加|参赛)?)"),
    ("fee_amount", r"(?P<seg>(?:报名费|参赛费|注册费|评审费)[^。；;\n]{0,10}?(?:为|是|：|:)?\s*[\d,，.]{1,8}\s*元)"),
    ("fee_amount2", r"(?P<seg>[\d,，.]{1,8}\s*元\s*/?\s*(?:人|队|支)?[^。；;\n]{0,6}(?:报名|参赛|注册)?费?)"),
]

TEAM_PATTERNS = [
    ("team_size", r"(?P<seg>(?:每队|每支队伍|每个团队|每组|每校)[^。；;\n]{0,12}?\d{1,2}\s*(?:[-~—至－]\s*\d{1,2}\s*)?人)"),
    ("team_rule", r"(?P<seg>(?:组队|团队形式|以团队|可跨校|可跨专业)[^。；;\n]{0,20})"),
    ("solo_rule", r"(?P<seg>(?:个人赛|单人参赛|以个人名义参赛|个人形式)[^。；;\n]{0,15})"),
]

ELIGIBILITY_PATTERNS = [
    ("eligibility", r"(?:参赛|报名)(?:对象|资格|范围|条件)[^。；;]{0,4}?[:：为]\s*(?P<seg>[^。；;\n]{0,60})"),
    ("eligibility2", r"(?P<seg>(?:全日制)?(?:在校)?(?:本科生|本科学生|研究生|专科生|学生)[^。；;\n]{0,25}?(?:均可|可以|均可报名|参加))"),
    ("grade_limit", r"(?P<seg>(?:限|仅限|面向)[^。；;\n]{0,6}(?:年级|大一|大二|大三|大四|一至|1-3|202\d级)[^。；;\n]{0,20})"),
]

ORGANIZER_PATTERNS = [
    ("organizer", r"(?:主办单位|主办方|主办)[^。；;]{0,3}?[:：为]\s*(?P<seg>[^。；;\n]{0,60})"),
    ("undertaker", r"(?:承办单位|承办方|承办)[^。；;]{0,3}?[:：为]\s*(?P<seg>[^。；;\n]{0,60})"),
    ("organized_by", r"由(?P<seg>[^。；;\n]{2,40}?)(?:主办|承办|协办)"),
]


def extract_fields(
    title: str,
    body: str,
    url: str,
    external_links: list[dict] | None = None,
    published_at: str | None = None,
) -> dict:
    """抽取一条通知的结构化信息；所有字段均为 Evidence 列表。"""
    text = (title or "") + "\n" + (body or "")
    # 网页中的 "2026年11月2.大数据挑战赛" 是"11月"后接第2个小节，
    # 不是11月2日。把日期/数字后紧跟中文的英文点恢复为句界。
    text = re.sub(r"\.(?=[\u4e00-\u9fff])", "。", text)
    base_year = None
    if published_at:
        m = re.match(r"(20\d{2})", published_at)
        if m:
            base_year = int(m.group(1))
    base_year = base_year or guess_publish_year(text)

    result: dict[str, list[dict]] = {}
    groups = {
        "registration": REGISTRATION_PATTERNS,
        "submission": SUBMISSION_PATTERNS,
        "contest_time": CONTEST_TIME_PATTERNS,
        "fee": FEE_PATTERNS,
        "team": TEAM_PATTERNS,
        "eligibility": ELIGIBILITY_PATTERNS,
        "organizer": ORGANIZER_PATTERNS,
    }
    # 时间类字段必须抽出真实日期，抽不到就留空，避免把"报名方式：xxx"当成时间
    date_required = {"registration", "submission", "contest_time"}
    for field, patterns in groups.items():
        items = _collect(
            text, patterns, field, base_year=base_year, require_date=field in date_required
        )
        result[field] = [e.as_dict() for e in items]
    result["award_ratio"] = _extract_award_ratios(text)

    # 日程按日期上下文逐条识别，避免一个长段落只保留第一个日期。
    schedule_seen = {item["value"] for item in result["contest_time"]}
    for item in find_dates(text, base_year):
        before = text[max(0, item["start"] - 60):item["start"]]
        after = text[item["end"]:item["end"] + 60]
        context = before + text[item["start"]:item["end"]] + after
        if not STAGE_CONTEXT_RE.search(context):
            continue
        if re.search(r"报名|注册|截止|截至", before[-60:]):
            continue
        if item["value"] in schedule_seen:
            continue
        schedule_seen.add(item["value"])
        result["contest_time"].append(
            Evidence(
                field="contest_time",
                value=item["value"],
                evidence=snippet_around(text, item["start"], item["end"], 55),
                method="date-context:stage",
            ).as_dict()
        )

    # 报名日期按语义分组：同一证据内多个日期视为起止，单日期按 method 判断。
    grouped: dict[tuple[str, str], list[dict]] = {}
    for item in result["registration"]:
        key = (item["method"], item["evidence"])
        grouped.setdefault(key, []).append(item)
    for (method, _evidence), items in grouped.items():
        dates = sorted(items, key=lambda item: item["value"])
        if method.endswith(
            ("reg_deadline", "reg_deadline2", "reg_before", "reg_from_now")
        ):
            for item in dates:
                item["role"] = "deadline"
        elif len(dates) >= 2 and method.endswith(("reg_window", "reg_colon", "reg_from_now")):
            dates[0]["role"] = "open"
            dates[-1]["role"] = "deadline"
        elif len(dates) == 1 and re.search(r"截至|截止|前", _evidence):
            dates[0]["role"] = "deadline"
        else:
            for item in dates:
                item.setdefault("role", "unclassified")

    # 正文里出现的所有日期，作为兜底时间线索（不指定语义）
    result["dates_all"] = [d["value"] for d in find_dates(text, base_year)][:20]

    if external_links:
        result["external_links"] = external_links[:10]
    return result


def summarize_dates(extracted: dict) -> dict:
    """把抽取结果压成便于排序/提醒的摘要字段。"""
    reg = extracted.get("registration", [])
    reg_dates = sorted({
        e["value"] for e in reg if re.match(r"20\d{2}-\d{2}-\d{2}", e["value"])
    })
    open_dates = sorted({
        e["value"] for e in reg
        if e.get("role") == "open" and re.match(r"20\d{2}-\d{2}-\d{2}", e["value"])
    })
    deadlines = sorted({
        e["value"] for e in reg
        if e.get("role") == "deadline" and re.match(r"20\d{2}-\d{2}-\d{2}", e["value"])
    })
    from datetime import date

    future_deadlines = [d for d in deadlines if d >= date.today().isoformat()]
    return {
        "registration_first": (open_dates or reg_dates or [None])[0],
        "registration_last": (deadlines or reg_dates or [None])[-1],
        "registration_next": future_deadlines[0] if future_deadlines else None,
        "registration_deadlines": deadlines,
        "registration_raw": [e["evidence"] for e in reg][:3],
    }


def _extract_award_ratios(text: str) -> list[dict]:
    """抽取明确的获奖比例。显式“获奖比例”优先，其次汇总各等级比例。"""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for clause in re.split(r"[。；;\n]", text):
        if not AWARD_LEVEL_RE.search(clause) and "获奖比例" not in clause and "获奖率" not in clause:
            continue
        total_match = AWARD_RATIO_TOTAL_RE.search(clause)
        if total_match:
            key = ("award_ratio_total", clause.strip()[:200])
            if key not in seen:
                seen.add(key)
                out.append({
                    "field": "award_ratio",
                    "value": f"{float(total_match.group('pct')):g}%",
                    "evidence": clause.strip()[:180],
                    "method": "award_ratio_total",
                    "role": "total",
                })
            continue
        percentages = [float(value) for value in PERCENT_RE.findall(clause)]
        if not percentages:
            continue
        # “前10%—25%”是累计名次门槛，不能把两个边界相加。
        total = max(percentages) if "前" in clause else min(100.0, sum(percentages))
        key = ("award_ratio_sum", clause.strip()[:200])
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "field": "award_ratio",
            "value": f"{total:g}%",
            "evidence": clause.strip()[:180],
            "method": "award_level_sum",
            "role": "aggregate",
        })
    return out[:3]


def summarize_award_ratio(extracted: dict) -> dict:
    items = extracted.get("award_ratio") or []
    if not items:
        return {"percent": None, "text": "", "method": ""}
    explicit = next(
        (item for item in items if item.get("method") == "award_ratio_total"),
        items[0],
    )
    value = str(explicit.get("value", "")).rstrip("%")
    try:
        percent = float(value)
    except ValueError:
        percent = None
    return {
        "percent": percent,
        "text": explicit.get("evidence", ""),
        "method": explicit.get("method", ""),
    }


def summarize_preparation(record: dict) -> dict:
    """计算报名确认后到最早比赛日之间的可用备赛窗口。"""
    deadline = record.get("registration_next") or record.get("registration_last")
    if not deadline:
        return {"days": None, "contest_date": None}
    try:
        deadline_date = date.fromisoformat(str(deadline)[:10])
    except ValueError:
        return {"days": None, "contest_date": None}
    contest_dates = []
    for item in record.get("contest_time_evidence") or []:
        try:
            contest_date = date.fromisoformat(str(item.get("value", ""))[:10])
        except ValueError:
            continue
        if contest_date >= deadline_date:
            contest_dates.append(contest_date)
    if not contest_dates:
        return {"days": None, "contest_date": None}
    first = min(contest_dates)
    return {"days": (first - deadline_date).days, "contest_date": first.isoformat()}
