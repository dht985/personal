"""从"赛事难度"和"官方要求"判断：这项赛事需要导师指导，还是学生能自主完成。"""

from __future__ import annotations

import re

from .textutil import clean_text, snippet_around

MENTOR_REQUIRED_RE = [
    ("须配备指导教师", r"(?:须|必须|需|应当|原则上)[^。；;\n]{0,12}(?:配备|安排|有)[^。；;\n]{0,8}(?:指导)?(?:教师|老师|教练)"),
    ("指导教师要求", r"指导教师[^。；;\n]{0,10}(?:不少于|至少|不超过|限)[^。；;\n]{0,10}"),
    ("学校推荐", r"(?:经|由)[^。；;\n]{0,10}(?:学校|学院|教务)[^。；;\n]{0,10}(?:推荐|审核)"),
    ("单位盖章", r"(?:加盖|盖)[^。；;\n]{0,8}(?:公章|印章)"),
]

SELF_RE = [
    ("个人参赛", r"个人赛|以个人名义|个人形式参赛|单人参赛"),
    ("自行报名", r"自行(?:注册|报名|登录)|自主报名|个人自行"),
    ("官网自行注册", r"(?:登录|访问)[^。；;\n]{0,20}(?:官网|平台)[^。；;\n]{0,24}(?:注册|报名)"),
    ("无需导师", r"(?:无需|不需要|不要求)[^。；;\n]{0,6}(?:指导)?(?:教师|老师)"),
]

# 注意不要把"实物"算进来：很多比赛的奖金写"奖金/实物激励"，那是奖品不是硬件。
HARDWARE_RE = re.compile(r"机器人|智能车|智能汽车|嵌入式|电子设计|机械结构|硬件|整车|元器件|焊接|飞控|无人机")
ALGO_RE = re.compile(r"程序设计|算法|编程|在线评测|OJ|代码|软件测试|数据结构")
PURE_ALGO_NAME_RE = re.compile(r"程序设计|算法|编程")
GRAD_RE = re.compile(r"研究生组|博士生|硕士生组|专业组")
TEAM_RE = re.compile(r"每队[^。；;\n]{0,12}?(\d{1,2})\s*(?:[-~—至]\s*(\d{1,2})\s*)?人")


def _find(body: str, patterns) -> list[tuple[str, str]]:
    out = []
    for label, pat in patterns:
        m = re.search(pat, body)
        if m:
            out.append((label, snippet_around(body, m.start(), m.end(), 40)))
    return out


def assess_requirement(record: dict) -> dict:
    """返回 {mentor_dependency, difficulty, reasons, evidence}。"""
    body = " ".join(
        clean_text((n.get("body_excerpt") or "") + " " + (n.get("title") or ""))
        for n in record.get("notices", [])
    )
    name = record.get("name", "")
    text = name + " " + body + " " + (record.get("team_text") or "") + " " + (
        record.get("eligibility_text") or ""
    )

    reasons: list[str] = []
    evidence: list[dict] = []

    mentor_hits = _find(text, MENTOR_REQUIRED_RE)
    self_hits = _find(text, SELF_RE)
    hardware_terms = HARDWARE_RE.findall(text)
    hardware_count = len(hardware_terms)
    algo_terms = ALGO_RE.findall(text)
    algo_count = len(algo_terms)
    hardware_heavy = hardware_count >= 2 and hardware_count > algo_count
    hardware = HARDWARE_RE.search(text)
    algo = ALGO_RE.search(text)
    grad = GRAD_RE.search(text)

    team_sizes = []
    for m in TEAM_RE.finditer(text):
        team_sizes.append(int(m.group(2) or m.group(1)))
    max_team = max(team_sizes) if team_sizes else 0

    # ---- 难度评分 1..4 ----
    level = 2
    if hardware_heavy:
        level += 1
        reasons.append("涉及实物/硬件或实验环境")
        evidence.append({"field": "难度", "snippet": snippet_around(text, hardware.start(), hardware.end(), 40)})
    elif hardware:
        reasons.append("部分赛项涉及嵌入式/硬件，可能需要实验条件")
    if max_team >= 5:
        level += 1
        reasons.append(f"团队规模较大（最多 {max_team} 人）")
    if grad:
        level += 1
        reasons.append("设有研究生组/专业组")
        evidence.append({"field": "难度", "snippet": snippet_around(text, grad.start(), grad.end(), 40)})
    if PURE_ALGO_NAME_RE.search(name) and self_hits and not hardware_heavy and max_team <= 3:
        level -= 1
        reasons.append("以编程/算法题为主，个人可独立完成")
    level = max(1, min(4, level))
    difficulty = {1: "入门", 2: "中等", 3: "较高", 4: "很高"}[level]

    # ---- 导师依赖 ----
    if mentor_hits:
        mentor = "required"
        reasons.append("官方要求明确提到指导教师/学校推荐/盖章")
        for label, snip in mentor_hits[:2]:
            evidence.append({"field": "官方要求", "snippet": snip, "label": label})
    elif hardware_heavy or level >= 4:
        mentor = "required"
        reasons.append("难度较高或需要实验条件，建议有导师带")
    elif self_hits and level <= 2:
        mentor = "self"
        reasons.append("无导师要求，且属于个人可完成的操作")
        for label, snip in self_hits[:2]:
            evidence.append({"field": "官方要求", "snippet": snip, "label": label})
    elif self_hits:
        mentor = "pending"
        reasons.append("允许个人报名，但难度不低，建议先确认是否需要指导")
    else:
        mentor = "pending"
        reasons.append("通知中未明确说明是否必须配备指导教师")

    # 目录里的承办学院/负责人说明"有导师资源"，但不等于"必须有导师"
    if record.get("catalog_dept") and record.get("catalog_dept") not in ("", "未标注"):
        reasons.append(f"目录注明承办单位 {record['catalog_dept']}，可向其确认指导资源")

    return {
        "mentor_dependency": mentor,
        "difficulty": difficulty,
        "difficulty_level": level,
        "reasons": reasons,
        "evidence": evidence[:6],
    }
