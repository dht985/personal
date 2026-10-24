"""查看每项赛事的云大生态评估与完成方式判断。"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
data = json.loads((ROOT / "data" / "candidates.json").read_text(encoding="utf-8"))

LABEL = {"sufficient": "充足", "inconclusive": "证据不充分", "insufficient": "不足"}
MENTOR = {"required": "需导师", "self": "可自主", "pending": "待确认"}


def show(r):
    p = r.get("ynu_profile") or {}
    verdict = p.get("verdict", "?")
    dims = {d["key"]: d["status"] for d in p.get("dimensions", [])}
    print(f"  [{LABEL.get(verdict, verdict):<6}] {r['name'][:34]:<36} "
          f"{r.get('difficulty', '?'):<3} {MENTOR.get(r.get('mentor_dependency'), '?')}")
    print(f"      知名度={dims.get('awareness','-')} 导师={dims.get('mentor','-')} "
          f"获奖={dims.get('awards','-')} 查询={p.get('queries_run',0)}"
          f" 目录内={p.get('in_catalog')}")
    for note in (p.get("notes") or [])[:2]:
        print(f"      注：{note}")
    for reason in (r.get("requirement") or {}).get("reasons", [])[:2]:
        print(f"      因：{reason}")
    for dim in (p.get("dimensions") or []):
        if dim.get("status") == "found":
            ev = (dim.get("evidence") or [{}])[0]
            print(f"      {dim['label']}依据：{ev.get('source','')} | {ev.get('url','')[:70]}")
            if ev.get("snippet"):
                print(f"         {ev['snippet'][:80]}")


print(f"纳入 {len(data['records'])} 项 / 排除 {len(data.get('excluded', []))} 项")
print("\n== 纳入 ==")
for rec in data["records"]:
    show(rec)
if data.get("excluded"):
    print("\n== 已排除 ==")
    for rec in data["excluded"]:
        show(rec)

unmatched = {}
for item in data.get("discovery", []):
    if item.get("kept") and not item.get("catalog_category"):
        title = item.get("title", "")
        unmatched[title] = item.get("real_url", "")
print(f"\n== 发现通道里未匹配目录的结果：{len(unmatched)} 条 ==")
for title, url in list(unmatched.items())[:25]:
    print(f"  {title[:56]}")
    print(f"      {url[:90]}")
