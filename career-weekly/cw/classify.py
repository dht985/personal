from __future__ import annotations

import re

SIGNALS = [
    ("招聘", r"招聘|校招|校园招聘|人才引进|应届|岗位|实习|统招|招录|招募"),
    (
        "政策",
        r"政策|发展规划|规划计划|规划纲要|专项规划|战略规划|五年规划|"
        r"指导意见|管理办法|实施细则|若干措施|行动方案|实施方案|"
        r"标准|规范|制度|工作方案|信息公开|年度报告|社会责任|"
        r"可持续发展|白皮书|薪酬情况",
    ),
    ("采购", r"采购|招标|中标|供应商|询价|比选"),
    ("项目", r"招标|采购|中标|项目|建设|开工|签约|交付"),
    ("投资", r"投资|增资|募资|基金|并购|重组|产投|融资"),
    ("战略", r"工作会议|战略|规划|部署|党组|党委|学习贯彻|年度工作|座谈会|合作"),
    ("技术", r"技术|研发|实验室|平台|成果|发布|应用|创新|突破"),
]

# 与职业选择无关的党务/宣传类内容
NOISE_RE = re.compile(
    r"巡视|纪检|主题教育|中国之治|宣传|庆祝|纪念|学习贯彻|政治局|总书记|党组|党委"
)
RECRUIT_RE = re.compile(r"招聘|校招|实习|人才引进")
CAMPUS_RE = re.compile(r"校园招聘|校招|应届")
POLICY_RE = re.compile(
    r"政策|发展规划|规划计划|规划纲要|专项规划|战略规划|五年规划|"
    r"指导意见|管理办法|实施细则|若干措施|行动方案|实施方案|"
    r"标准|规范|制度|工作方案|通知|公告|公示|年度报告|社会责任|"
    r"可持续发展|白皮书|薪酬情况"
)
TECH_RE = re.compile(
    r"软件|信息|计算机|电子|通信|数据|自动化|算法|研发|技术|信息化|人工智能|网络|系统|芯片"
)
# 行业硬相关词：避免把首页转载的无关时政/别家公司新闻收进来
INDUSTRY_RE = re.compile(
    r"电力|电网|能源|石油|天然气|管网|煤炭|新能源|光伏|风电|核电|储能|"
    r"航空|航天|船舶|兵器|军工|装备|电子|芯片|软件|系统|平台|数据|"
    r"人工智能|算法|机器人|智能制造|信息化|通信"
)


def is_relevant(title: str, source_purpose: str | None = None) -> bool:
    if NOISE_RE.search(title):
        return False
    if RECRUIT_RE.search(title):
        # 校园招聘面向多专业，保留；社会招聘要求技术相关，避免审计/财务岗混入
        return bool(
            source_purpose == "recruit"
            or CAMPUS_RE.search(title)
            or TECH_RE.search(title)
        )
    if source_purpose == "policy" and POLICY_RE.search(title):
        return True
    return bool(INDUSTRY_RE.search(title))


def signal_type(title: str) -> str | None:
    # “国家能源投资集团”等单位专名中的“投资”不是新闻信号。
    normalized = re.sub(
        r"(国家能源投资集团|国家电力投资集团|国家开发投资集团)"
        r"(?:有限责任公司|有限公司|集团)?",
        "",
        title,
    )
    for name, pattern in SIGNALS:
        if re.search(pattern, normalized):
            return name
    return None


def match_tracks(title: str, tracks: list[dict]) -> list[str]:
    return [t["id"] for t in tracks if any(k in title for k in t.get("keywords", []))]


def match_tags(title: str, tags: list[dict]) -> list[str]:
    return [t["id"] for t in tags if any(k in title for k in t.get("keywords", []))]
