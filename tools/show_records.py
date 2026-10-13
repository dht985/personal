"""调试用：打印最近一次运行的结构化结果。"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
root = Path(__file__).resolve().parents[1]
data = json.loads((root / "data" / "candidates.json").read_text(encoding="utf-8"))

print("stats:", json.dumps(data["stats"], ensure_ascii=False))
print("\nfetch log:")
for row in data["fetch_log"]:
    print("  ", row)

print("\nrecords:")
for r in data["records"]:
    print(f"  [{r['tier']}] {r['score_total']}  {r['name']}")
    print(f"      catalog={r.get('catalog_category')}#{r.get('catalog_no')} "
          f"fit={r.get('cs_fit')} deadline={r.get('registration_last')} "
          f"notices={len(r['notices'])}")
    for n in r["notices"][:3]:
        print(f"        - {n['title'][:58]}  {n['url'][:72]}")
    for ev in (r.get("registration_evidence") or [])[:2]:
        print(f"        * 依据: {ev.get('evidence', '')[:90]}")

print("\n综测赋分维度抽样:")
for r in data["records"][:6]:
    dim = next((d for d in r.get("dimensions", []) if d["key"] == "acceptance"), None)
    if dim:
        print(f"  {r['name'][:26]}")
        print(f"      目录类别(2026)={r.get('catalog_category')} / (2025)={r.get('catalog_category_prev')}"
              f"  status={dim['status']} score={dim['score']}")
        print(f"      {dim['detail'][:150]}")

print("\ndiscovery kept:")
for d in data.get("discovery", []):
    if d.get("kept"):
        print(f"  - {d['title'][:60]} | {d.get('real_url', '')[:80]}")
