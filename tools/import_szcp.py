"""从《计科综合评测细则》PDF 解析综测加分规则，生成 data/szcp_college.json。

刻意用正则从原文里抓数字，而不是手抄：这样换一版细则时能看出数字变了，
抓不到关键项就直接报错，避免悄悄用错的分值。

用法:
    python tools/extract_pdf_text.py <细则.pdf> data/raw/szcp_xueyuan.txt
    python tools/import_szcp.py data/raw/szcp_xueyuan.txt data/raw/szcp_xueyuan_v3.2.pdf
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _need(pattern: str, text: str, label: str, group: int = 1) -> str:
    m = re.search(pattern, text)
    if not m:
        raise SystemExit(f"解析失败：找不到「{label}」，请人工核对细则原文后再调整解析规则。\n"
                         f"  用于匹配的模式：{pattern}")
    return m.group(group)


def _need_match(pattern: str, text: str, label: str) -> re.Match:
    m = re.search(pattern, text)
    if not m:
        raise SystemExit(f"解析失败：找不到「{label}」，请人工核对细则原文后再调整解析规则。\n"
                         f"  用于匹配的模式：{pattern}")
    return m


def parse(text: str) -> dict:
    # PDF 正文会在句子中间换行（例如"团队内排名第\n一权重为 1"），
    # 规则类句子统一在去掉换行的副本上匹配；表格仍用原文，避免把"0.7"和下一行的"6"粘成"0.76"。
    flat = text.replace("\n", "")
    cap = float(_need(r"本项加分上限\s*([\d.]+)\s*分", flat, "G22 加分上限"))
    base_national = float(_need(
        r"国家级（含跨境赛事或项目）比赛竞赛获奖[^0-9]{0,20}([\d.]+)\s*分", flat, "国家级基础分"))
    base_provincial = float(_need(r"省级比赛竞赛获奖[^0-9]{0,20}([\d.]+)\s*分", flat, "省级基础分"))

    # 目录页里也有"竞赛分类等级及权重"这几个字，所以要试每一个出现位置，
    # 取第一个能解析出完整四行的窗口。
    category_weight: dict[str, float] = {}
    for hit in re.finditer("竞赛分类等级", text):
        window = text[hit.start(): hit.start() + 300]
        found = dict(re.findall(r"(一类|二类|三类|四类)\s+([\d.]+)", window))
        if len(found) == 4:
            category_weight = {k: float(v) for k, v in found.items()}
            break
    if len(category_weight) != 4:
        raise SystemExit(f"解析失败：竞赛分类等级权重只解析到 {category_weight}")
    category_weight["五类"] = float(_need(r"五类竞赛权重确定为\s*([\d.]+)", flat, "五类权重"))

    award = _need_match(
        r"一等及以上权重为\s*([\d.]+)\s*[；;]\s*二等权重为\s*([\d.]+)\s*[；;]"
        r"\s*三等权重为\s*([\d.]+)\s*[,，]\s*其他等级权重为\s*([\d.]+)",
        flat, "获奖等级权重",
    )
    award_weight = dict(
        zip(["一等及以上", "二等", "三等", "其他"],
            (float(x) for x in award.groups()))
    )

    rank = _need_match(
        r"排名第一权重为\s*([\d.]+)\s*[；;]\s*第二作者或排名第二权重为\s*([\d.]+)\s*[；;]"
        r"\s*第三作者或排名第三权重为\s*([\d.]+)\s*[；;]\s*其他等级排名权重为\s*([\d.]+)",
        flat, "团队排名权重",
    )
    rank_weight = dict(
        zip(["第一", "第二", "第三", "其他"], (float(x) for x in rank.groups()))
    )

    # 公式形如"成果加分=成果基础分×竞赛分类等级权重×获奖等级分值权重×团队排名分值权重"，
    # 用"每段以权重结尾"的结构来截断，避免把后面那句说明也吞进来。
    formula = _need(r"(成果加分\s*=\s*成果基础分(?:[×x][^×x]{2,20}?权重)+)", flat, "加分公式")
    return {
        "cap": cap,
        "base_score": {"国家级": base_national, "省级": base_provincial},
        "category_weight": category_weight,
        "award_weight": award_weight,
        "rank_weight": rank_weight,
        "formula": formula.replace(" ", ""),
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    text_path = Path(sys.argv[1])
    pdf_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("data/szcp_college.json")

    text = text_path.read_text(encoding="utf-8")
    rules = parse(text)

    title = "计算机科学与技术专业 2023 级综合评测细则"
    m = re.search(r"(2023\s*级计科综合评测细则)", text)
    if m:
        title = m.group(1)
    major = "计算机科学与技术" if "计算机科学与技术" in text else ""
    effective = "2025-2026 学年" if "2025-2026" in text or "2025.9.1-2026.8.31" in text else ""

    payload = {
        "meta": {
            "title": title,
            "applicable_major": major,
            "effective_year": effective,
            "local_file": str(pdf_path.as_posix()) if pdf_path else "",
            "sha256": hashlib.sha256(pdf_path.read_bytes()).hexdigest() if pdf_path else "",
            "text_source": str(text_path.as_posix()),
            "imported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "provenance": "由用户提供的《综测细则v3.2.pdf》解析而来；数值均来自原文，未人工改写。",
            "deprecation_rule": "列入 2025 年目录但未列入 2026 年目录的竞赛，按降一级处理；"
                                "四类降为五类，权重 0.6。",
        },
        "rules": rules,
        "notes": [
            "同一竞赛项目就高不就低，不累加。",
            "学业成绩 G21 由学生自行核算，综测小组审核。",
            "团队排名以获奖证书所列成员顺序为准；证书无法体现排序时需书面说明并共同签字。",
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"标题: {title}")
    print(f"适用专业: {major or '未识别'}  学年: {effective or '未识别'}")
    print(f"加分上限: {rules['cap']}")
    print(f"基础分: {rules['base_score']}")
    print(f"分类等级权重: {rules['category_weight']}")
    print(f"获奖等级权重: {rules['award_weight']}")
    print(f"团队排名权重: {rules['rank_weight']}")
    print(f"公式: {rules['formula']}")
    print(f"输出 -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
