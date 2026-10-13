"""演示/自检：给定一批真实通知标题，显示赛事名提取与目录匹配结果。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from radar.catalog import Catalog  # noqa: E402
from radar.extract import guess_competition_name  # noqa: E402

TITLES = [
    "关于组织参加2026年全国大学生软件测试大赛的通知",
    "第十七届蓝桥杯全国大学生软件和信息技术大赛软件类报名和校级选拔",
    "报名参加2026年“码蹄杯”程序设计大赛",
    "关于组织参加2026年第十一届“中国高校计算机大赛-团体程序设计天梯赛”的通知",
    "关于2026中国高校计算机大赛-大数据挑战赛报名的通知",
    "2026年第八届全国高校计算机能力挑战赛官网",
    "关于举办2026年第十九届全国大学生先进成图技术与产品信息建模创新大赛云南大学选拔赛的通知",
    "关于组织开展2026年“中国大学生计算机设计大赛”云南大学校级选拔赛的通知",
    "关于组织参加2026年中美青年创客大赛的通知",
    "关于举办2026年大学生新文科实践创新大赛云南大学校内选拔赛的通知",
    "关于组织开展2026年全国本科院校税收风险管控案例大赛云南大学校内选拔赛的通知",
]


def main() -> int:
    catalog = Catalog.load(ROOT / "data" / "catalog_ynu_2025.json")
    miss = 0
    for title in TITLES:
        guessed = guess_competition_name(title)
        entry, score, method = catalog.match(guessed)
        mark = "OK " if entry else "MISS"
        if not entry:
            miss += 1
        name = entry.name if entry else "—"
        cat = entry.category if entry else "—"
        print(f"{mark} {method:<13} {score:<6} {title[:30]:<32} => {name}（{cat}）")
    print(f"\n未匹配 {miss} / {len(TITLES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
