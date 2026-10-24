"""赛事价值评估：分维度计分 + 三级分层 + 可解释理由。

刻意把"目录认定 / 综测赋分 / 发展价值"拆成互相独立、各自留证的维度：
目录里有名字不代表综测会加分，综测加分也不等于保研有用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from .config import Config

NATIONAL_SIGNALS = ["教育部", "国务院", "共青团中央", "国家级", "全国", "国际"]
PROVINCIAL_SIGNALS = ["云南省教育厅", "云南省", "省级"]
ACADEMIC_SIGNALS = ["中国高等教育学会", "学会", "协会", "IEEE", "ACM", "CCF", "教育部高等学校"]
ENTERPRISE_SIGNALS = ["华为", "百度", "腾讯", "阿里", "字节", "西门子", "谷歌", "企业", "有限公司", "公司"]


@dataclass
class Dimension:
    key: str
    label: str
    score: float
    status: str  # verified | unverified | negative
    detail: str
    evidence: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "score": self.score,
            "status": self.status,
            "detail": self.detail,
            "evidence": self.evidence,
        }


def _has(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


_LEVEL_SIGNALS = (
    ("国家级", NATIONAL_SIGNALS),
    ("学会级", ACADEMIC_SIGNALS),
    ("省级", PROVINCIAL_SIGNALS),
    ("企业级", ENTERPRISE_SIGNALS),
)


def _level_of(segment: str) -> str:
    for level, signals in _LEVEL_SIGNALS:
        if any(s in segment for s in signals):
            return level
    return "未知"


def classify_organizer(text: str) -> tuple[str, str]:
    """依据原文判断主办方层级。返回 (层级, 依据片段)。

    关键是先锚定"主办单位/主办方"这类表述，只在锚点附近取词。
    否则省级选拔通知里一句"参加全国总决赛"就会把整场赛事误判成国家级。
    """
    # 1) "主办单位：X" / "主办方：X"
    for m in re.finditer(r"(?:主办单位|主办方)[^。；;\n]{0,4}?[:：]\s*([^。；;\n]{2,60})", text):
        seg = m.group(1).strip()
        level = _level_of(seg)
        if level != "未知":
            return level, seg

    # 2) "X主办，..." 这种主语在前的写法
    for m in re.finditer(r"([^。；;\n，,]{2,40}?)(?:联合)?主办", text):
        seg = m.group(1).strip()
        level = _level_of(seg)
        if level != "未知":
            return level, seg

    # 3) 没有明确主办表述时，逐句看，跳过"参加/选拔/晋级"这类参赛语境
    for sentence in re.split(r"[。；;\n]", text):
        if re.search(r"参加|参赛|选拔|晋级|进入|入围", sentence):
            continue
        level = _level_of(sentence)
        if level != "未知":
            return level, sentence.strip()[:80]
    return "未知", ""


def cs_fit(record: dict, cfg: Config) -> tuple[str, str]:
    """判断与计算机专业本科生的适配度。"""
    kw = cfg.keywords
    text = record.get("name", "") + " " + " ".join(
        n.get("title", "") for n in record.get("notices", [])
    )
    strong = [w for w in kw.get("cs_signals_strong", []) if w in text]
    weak = [w for w in kw.get("cs_signals_weak", []) if w in text]
    off_hits = [w for w in kw["off_domain"] if w in text]
    if strong and not off_hits:
        return "核心", "命中计算机核心关键词：" + "、".join(strong[:4])
    if len(weak) >= 2 and not off_hits:
        return "相关", "综合多项相关信号：" + "、".join(weak[:4])
    if record.get("catalog_dept") in ("软件学院", "信息学院"):
        return "核心", f"目录中由{record['catalog_dept']}承办"
    if strong or weak:
        return "相关", "命中相关关键词：" + "、".join((strong + weak)[:4])
    track_hits = [w for w in kw.get("always_track", []) if w in text]
    if track_hits:
        return "相关", "综合性高价值赛事（命中重点跟踪名单：" + "、".join(track_hits[:3]) + "）"
    if record.get("catalog_category") == "一类":
        return "相关", "学校认定目录中的一类赛事，可作为综合能力与保研材料支撑（非纯计算机赛道）"
    if off_hits:
        return "弱", "与计算机专业关联较弱：" + "、".join(off_hits[:3])
    return "弱", "未检出计算机相关关键词"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _deadline_status(record: dict, cfg: Config) -> tuple[str, str]:
    """返回 (时效状态, 说明)。"""
    th = cfg.scoring["thresholds"]
    today = date.today()
    last = _parse_date(record.get("registration_last"))
    if last is None:
        return "未找到日期", "通知中未抽取到明确的报名截止日期"
    days = (last - today).days
    if days < 0:
        return "已截止", f"报名截止 {last.isoformat()}（已过期 {-days} 天）"
    if days <= th["deadline_soon_days"]:
        return "30天内截止", f"报名截止 {last.isoformat()}，还剩 {days} 天"
    if days <= th["deadline_near_days"]:
        return "90天内截止", f"报名截止 {last.isoformat()}，还剩 {days} 天"
    return "报名开放", f"报名截止 {last.isoformat()}，还剩 {days} 天"


def _acceptance_dimension(
    cfg: Config, szcp: dict | None, szcp_rules, record: dict
) -> Dimension:
    """综合测评赋分维度。

    分三档，避免把"知道学校有综测加分"当成"知道这个赛事能加几分"：
    - 赛事级赋分已核实：拿到了学院（计科）细则里的权重表，能对具体赛事算出分值
    - 校级规则已核实：拿到了校级办法/测评表，知道加分模块与上限，但具体分值未定
    - 未核实：什么都没有
    """
    sc = cfg.scoring["acceptance_score"]

    # 第一优先：学院细则 + 已知分类等级 -> 可以直接算出来
    if szcp_rules is not None and getattr(szcp_rules, "available", False):
        category, downgraded_from = szcp_rules.resolve_category(
            record.get("catalog_category"), record.get("catalog_category_prev")
        )
        best = szcp_rules.estimate(category, downgraded_from=downgraded_from) if category else None
        evidence = [
            {
                "type": "document",
                "url": "",
                "role": f"学院细则（本地文件 {szcp_rules.meta.get('local_file', '')}）",
                "quote": f"{szcp_rules.meta.get('title', '')}："
                         f"成果加分=成果基础分×竞赛分类等级权重×获奖等级分值权重×团队排名分值权重，"
                         f"上限 {szcp_rules.rules.get('cap')} 分",
            }
        ]
        if best is not None:
            record["szcp_estimate"] = best.as_dict()
            detail = (
                f"赛事级赋分已核实（《{szcp_rules.meta.get('title', '计科综测细则')}》，"
                f"{szcp_rules.meta.get('applicable_major', '')}）："
                f"以「国家级一等奖 + 团队排名第一」为例，{best.formula}"
                f"（基础分 {best.base:g}、分类权重 {best.category_weight:g}、"
                f"获奖权重 {best.award_weight:g}、排名权重 {best.rank_weight:g}，"
                f"上限 {best.cap:g} 分）。"
            )
            if downgraded_from:
                detail += (
                    f" 注意：该赛事未列入 2026 版目录，按细则降一级处理"
                    f"（{downgraded_from} → {category}）。"
                )
            detail += " 二等/三等、排名靠后按权重递减；同一竞赛就高不就低，不累加。"
            return Dimension(
                key="acceptance", label="综合测评赋分",
                score=sc["赛事级赋分已核实"], status="verified",
                detail=detail, evidence=evidence,
            )
        return Dimension(
            key="acceptance", label="综合测评赋分",
            score=sc["校级规则已核实"], status="partially-verified",
            detail=(
                f"有学院细则，但该赛事既不在 2026 版目录也不在 2025 版目录中，"
                f"无法确定分类等级权重，所以算不出分值。"
                f"细则规定：列入 2025 年目录但未列入 2026 年目录的按降一级处理；"
                f"两版都没有的赛事需要先向学院确认。"
            ),
            evidence=evidence,
        )

    bonus = (szcp or {}).get("competition_bonus")
    if not bonus:
        return Dimension(
            key="acceptance",
            label="综合测评赋分",
            score=sc["未核实"],
            status="unverified",
            detail="尚未取得云南大学现行有效的本科生综合素质测评办法原文，"
                   "因此不对该赛事是否赋分、赋多少分下结论。",
            evidence=[{"type": "missing", "note": "需要人工提供或确认综测规则文件"}],
        )
    sources = (szcp.get("meta") or {}).get("sources", [])
    evidence = [
        {"type": "document", "url": s.get("url", ""), "role": s.get("role", ""),
         "quote": s.get("quote", "")}
        for s in sources[:3]
    ]
    return Dimension(
        key="acceptance",
        label="综合测评赋分",
        score=sc["校级规则已核实"],
        status="partially-verified",
        detail=(
            f"校级规则已核实（{ (szcp.get('meta') or {}).get('document_no', '') }）："
            f"{bonus.get('verified_conclusion', '')}"
            f"但 {bonus.get('open_question', '')}"
            "因此本维度只到校级，不判断该赛事具体加几分。"
        ),
        evidence=evidence,
    )


def evaluate(
    record: dict,
    cfg: Config,
    catalog_meta: dict,
    history_years: int = 0,
    szcp: dict | None = None,
    szcp_rules=None,
) -> dict:
    sc = cfg.scoring
    dimensions: list[Dimension] = []
    risks: list[str] = []
    actions: list[str] = []

    # ---- 维度 1：目录认定 -------------------------------------------
    cat = record.get("catalog_category")
    if cat and cat in sc["catalog_score"]:
        score = sc["catalog_score"][cat]
        dim = Dimension(
            key="catalog",
            label="云南大学认定目录",
            score=score,
            status="verified",
            detail=f"收录于《{catalog_meta.get('title', '云南大学认定本科生学科竞赛目录')}》，类别：{cat}",
            evidence=[
                {
                    "type": "catalog",
                    "source": catalog_meta.get("source_url", ""),
                    "attachment": catalog_meta.get("attachment_url", ""),
                    "version": catalog_meta.get("version", ""),
                    "entry_no": record.get("catalog_no"),
                    "match": record.get("catalog_match_method"),
                    "confidence": record.get("catalog_match_score"),
                }
            ],
        )
    else:
        dim = Dimension(
            key="catalog",
            label="云南大学认定目录",
            score=sc["catalog_score"]["未收录"],
            status="negative",
            detail=f"未匹配到《{catalog_meta.get('title', '云南大学认定本科生学科竞赛目录')}》中的条目。"
                   "可能是新赛事、名称差异过大，或本就不在校内认定范围内，需要人工复核。",
            evidence=[{"type": "catalog", "source": catalog_meta.get("source_url", "")}],
        )
    dimensions.append(dim)

    # ---- 维度 2：综合测评赋分 ---------------------------------------
    dimensions.append(_acceptance_dimension(cfg, szcp, szcp_rules, record))

    # ---- 维度 3：主办方与影响力 -------------------------------------
    body_text = " ".join(n.get("title", "") + " " + n.get("body_excerpt", "")
                         for n in record.get("notices", []))
    level, seg = classify_organizer(body_text)
    org_score = sc["organizer_score"].get(level, 0)
    dimensions.append(
        Dimension(
            key="organizer",
            label="主办方层级",
            score=org_score,
            status="verified" if level != "未知" else "unverified",
            detail=f"层级判断：{level}" if level != "未知" else "通知原文中未找到明确的主办单位表述",
            evidence=[{"type": "text", "snippet": seg}] if seg else [],
        )
    )

    fit, fit_reason = cs_fit(record, cfg)
    dimensions.append(
        Dimension(
            key="cs_fit",
            label="与计算机专业适配度",
            score=sc["cs_fit_score"][fit],
            status="derived",
            detail=f"适配度：{fit}。{fit_reason}",
        )
    )

    status, status_detail = _deadline_status(record, cfg)
    dimensions.append(
        Dimension(
            key="timeliness",
            label="时效性",
            score=sc["timeliness_score"][status],
            status="verified" if status != "未找到日期" else "unverified",
            detail=status_detail,
            evidence=record.get("registration_evidence", [])[:2],
        )
    )

    # ---- 维度 6：历年组织情况（用数据库历史，说明赛事是否持续举办）----
    hist_cfg = sc.get("history_score", {})
    if history_years >= 2:
        hist_score, hist_status = hist_cfg.get("两年及以上", 0), "verified"
        hist_detail = f"校内历年通知覆盖 {history_years} 个年度，赛事持续举办有据可查"
    elif history_years == 1:
        hist_score, hist_status = hist_cfg.get("仅一年", 0), "verified"
        hist_detail = "仅检索到 1 个年度的校内通知"
    else:
        hist_score, hist_status = hist_cfg.get("无历史记录", 0), "unverified"
        hist_detail = "库内没有该校赛的历年通知记录，可能尚未在校内组织过或记录不全"
    dimensions.append(
        Dimension(
            key="history",
            label="历年组织情况",
            score=hist_score,
            status=hist_status,
            detail=hist_detail,
        )
    )

    total = round(sum(d.score for d in dimensions), 1)
    verified_dims = sum(
        1 for d in dimensions if d.status in ("verified", "derived", "partially-verified")
    )

    # ---- 风险与行动 --------------------------------------------------
    if status == "未找到日期":
        risks.append("通知中未抽取到明确报名截止日期，需打开原文人工确认")
    if status == "30天内截止":
        actions.append(f"尽快报名：{status_detail}")
    fee = record.get("fee_text")
    if fee and not re.search(r"免费|不收取|无报名费", fee):
        risks.append(f"可能涉及费用：{fee}")
    if record.get("catalog_category") is None:
        risks.append(
            f"未收录于《{catalog_meta.get('title', '学校认定本科生学科竞赛目录')}》，"
            "参赛前建议先向学院/本科生院确认是否计入认定"
        )
    if not record.get("student_reviews"):
        risks.append("未找到足够可靠的公开学生评价")
    actions.append("核对官方通知原文中的报名入口与截止时间")
    if record.get("catalog_category") in ("一类", "二类"):
        actions.append("向承办学院（目录中已注明）确认校赛时间与名额分配")

    rules = sc["tier_rules"]
    fit_ok = fit in rules["focus_requires_cs_fit"]
    tier_rule = ""
    if not fit_ok:
        tier = "低优先级/证据不足"
        tier_rule = "与计算机专业适配度为弱，不进入重点关注"
    elif record.get("catalog_category") in rules["focus_categories"]:
        tier = "重点关注"
        tier_rule = f"学校认定目录 {record['catalog_category']} 赛事"
    elif total >= rules["focus_min_score"] and verified_dims >= rules["focus_min_dimensions"]:
        tier = "重点关注"
        tier_rule = f"总分 {total} ≥ {rules['focus_min_score']}，且有据可查的维度 {verified_dims} 个"
    elif (
        fit == "核心"
        and status == "30天内截止"
        and total >= rules["focus_actionable_min_score"]
    ):
        tier = "重点关注"
        tier_rule = "计算机核心赛道且 30 天内截止，可立即行动"
    elif total >= rules["potential_min_score"]:
        tier = "潜在机会"
        tier_rule = f"总分 {total} 达到潜在机会线（{rules['potential_min_score']}）"
    else:
        tier = "低优先级/证据不足"
        tier_rule = f"总分 {total} 偏低，证据与价值均不足"
    record["tier_rule"] = tier_rule

    # 只有获奖新闻、没有任何报名/通知信息的赛事，不能进入"重点关注"
    if not record.get("notices") and tier == "重点关注":
        tier = "潜在机会"
        record["tier_rule"] = "仅找到获奖新闻，缺少本年度报名通知，降为潜在机会"
        risks.append("本轮只找到获奖新闻，未找到本年度报名通知，需人工确认是否仍在校内组织")

    record["dimensions"] = [d.as_dict() for d in dimensions]
    record["score_total"] = total
    record["verified_dimensions"] = verified_dims
    record["tier"] = tier
    record["risks"] = risks
    record["next_actions"] = actions
    record["cs_fit"] = fit
    record["deadline_status"] = status
    record["deadline_detail"] = status_detail
    return record


def explain_tier(record: dict) -> str:
    cat = record.get("catalog_category") or "未收录"
    return (
        f"{record.get('tier_rule', '')}；"
        f"总分 {record['score_total']}（目录 {cat} / 适配 {record.get('cs_fit')} / "
        f"有据可查维度 {record['verified_dimensions']} 个）"
    )
