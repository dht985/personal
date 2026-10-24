"""验证主办方层级判定在省级选拔通知上的表现。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from radar.evaluate import classify_organizer  # noqa: E402

CASES = [
    ("省级选拔含全国总决赛",
     "云南省教育厅主办，云南省大学生竞赛组委会承办。选拔优秀队伍参加全国总决赛。"),
    ("明确主办单位",
     "主办单位：云南省教育厅。承办单位：云南大学。优秀队伍参加全国总决赛。"),
    ("全国性赛事",
     "主办单位：教育部高等学校计算机类专业教学指导委员会。"),
    ("没有主办表述",
     "现将有关事项通知如下，请各学院组织学生参加全国总决赛。"),
]

for label, text in CASES:
    level, seg = classify_organizer(text)
    print(f"{label}: {level}")
    print(f"    依据: {seg[:80]}")
