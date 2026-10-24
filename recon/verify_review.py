"""逐条核实外部评审意见里的事实性断言。"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from radar.catalog import Catalog  # noqa: E402


def show(title, ok, detail=""):
    print(f"[{'确认' if ok else '不成立'}] {title}" + (f" —— {detail}" if detail else ""))


print("=" * 72)
cat = Catalog.load(ROOT / "data" / "catalog_ynu_2026.json")
for name in ["美国大学生数学建模竞赛", "亚太地区大学生数学建模竞赛",
             "全国大学生数学建模竞赛"]:
    entry, score, method = cat.match(name)
    print(f"  match({name}) -> {entry.name if entry else None} "
          f"({entry.category if entry else '-'}) score={score} method={method}")

print("=" * 72)
radar = ROOT / "radar"
for f in sorted(radar.glob("*.py")):
    text = f.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if "2025" in line:
            print(f"  2025 残留 {f.name}:{i}: {line.strip()[:110]}")

print("=" * 72)
report = (radar / "report.py").read_text(encoding="utf-8")
for i, line in enumerate(report.splitlines(), 1):
    if "未核实" in line:
        print(f"  未核实 {i}: {line.strip()[:110]}")

print("=" * 72)
readme = (ROOT / "README.md").read_text(encoding="utf-8")
for i, line in enumerate(readme.splitlines(), 1):
    if re.search(r"满分|≥\s*6\d|管理员|250 次|360 搜索", line):
        print(f"  README {i}: {line.strip()[:110]}")

print("=" * 72)
kw = (ROOT / "config" / "keywords.toml").read_text(encoding="utf-8")
queries = re.findall(r'^q\s*=\s*"(.+)"', kw, re.M)
print(f"  发现检索式总数: {len(queries)}，去重后 {len(set(queries))}")
for q in sorted({q for q in queries if queries.count(q) > 1}):
    print(f"    重复: {q}")

print("=" * 72)
store = (radar / "store.py").read_text(encoding="utf-8")
for i, line in enumerate(store.splitlines(), 1):
    if "catalog:<" in line:
        print(f"  store 文档 {i}: {line.strip()[:110]}")

print("=" * 72)
notify = (radar / "notify.py").read_text(encoding="utf-8")
for i, line in enumerate(notify.splitlines(), 1):
    if "__import__" in line:
        print(f"  notify hack {i}: {line.strip()[:110]}")
