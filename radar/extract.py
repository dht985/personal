"""规则抽取：从通知标题与正文中抽取可溯源的字段（日期、费用、组队、主办等）。

设计原则：每一个抽取结果都携带原文片段，抽不到就返回空，不做推测。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .textutil import find_dates, guess_publish_year, snippet_around, squeeze


@dataclass
class Evidence:
    field: str
    value: str
    evidence: str
    method: str

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
    ("reg_deadline", r"(?:报名|网上报名|预报名)?[^。；;]{0,8}?(?:截止|截至)(?:时间|日期)?[^。；;]{0,4}?[:：为]?\s*(?P<seg>[^。；;\n]{0,60})"),
    ("reg_window", r"(?:报名|参赛报名)(?:时间|日期|期限)[^。；;]{0,4}?[:：为]\s*(?P<seg>[^。；;\n]{0,60})"),
    ("reg_colon", r"报名[^。；;\n]{0,15}?[:：]\s*(?P<seg>[^。；;\n]{0,60})"),
    ("reg_from_now", r"即日起至(?P<seg>[^。；;\n]{0,40})"),
    ("reg_before", r"(?:于|在)(?P<seg>[^。；;\n]{0,30}?)前[^。；;\n]{0,10}?(?:报名|提交|报送|注册|完成报名)"),
    ("reg_deadline2", r"(?:报名)?截止日期(?:为|是)?[:：]?\s*(?P<seg>[^。；;\n]{0,40})"),
    ("submit_deadline", r"(?:提交|报送|上传)[^。；;]{0,6}?(?:截止|截至)(?:时间|日期)?[^。；;]{0,4}?[:：为]?\s*(?P<seg>[^。；;\n]{0,50})"),
]

CONTEST_TIME_PATTERNS = [
    ("contest_time", r"(?:竞赛|比赛|大赛|赛事|决赛|初赛|省赛|国赛)[^。；;]{0,6}?时间[^。；;]{0,4}?[:：为]\s*(?P<seg>[^。；;\n]{0,60})"),
    ("contest_hold", r"(?:拟)?(?:于|在)\s*(?P<seg>[^。；;\n]{0,30}?)(?:举行|举办|进行)"),
    ("stage_time", r"(?P<seg>(?:校赛|校内选拔赛|省级|省赛|国赛|全国总决赛|决赛)[^。；;\n]{0,20}?)(?:时间|安排)[^。；;]{0,4}?[:：为]\s*(?P<seg2>[^。；;\n]{0,40})"),
]

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
    base_year = None
    if published_at:
        m = re.match(r"(20\d{2})", published_at)
        if m:
            base_year = int(m.group(1))
    base_year = base_year or guess_publish_year(text)

    result: dict[str, list[dict]] = {}
    groups = {
        "registration": REGISTRATION_PATTERNS,
        "contest_time": CONTEST_TIME_PATTERNS,
        "fee": FEE_PATTERNS,
        "team": TEAM_PATTERNS,
        "eligibility": ELIGIBILITY_PATTERNS,
        "organizer": ORGANIZER_PATTERNS,
    }
    # 时间类字段必须抽出真实日期，抽不到就留空，避免把"报名方式：xxx"当成时间
    date_required = {"registration", "contest_time"}
    for field, patterns in groups.items():
        items = _collect(
            text, patterns, field, base_year=base_year, require_date=field in date_required
        )
        result[field] = [e.as_dict() for e in items]

    # 正文里出现的所有日期，作为兜底时间线索（不指定语义）
    result["dates_all"] = [d["value"] for d in find_dates(text, base_year)][:20]

    if external_links:
        result["external_links"] = external_links[:10]
    return result


def summarize_dates(extracted: dict) -> dict:
    """把抽取结果压成便于排序/提醒的摘要字段。"""
    reg = extracted.get("registration", [])
    reg_dates = sorted({e["value"] for e in reg if re.match(r"20\d{2}-\d{2}-\d{2}", e["value"])})
    return {
        "registration_first": reg_dates[0] if reg_dates else None,
        "registration_last": reg_dates[-1] if reg_dates else None,
        "registration_raw": [e["evidence"] for e in reg][:3],
    }
