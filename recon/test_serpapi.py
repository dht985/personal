"""验证 SerpApi 百度引擎：连通性、返回结构、云大覆盖。"""

import json
import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

key = (os.environ.get("COMPRADAR_SERPAPI_KEY") or "").strip()
if not key:
    print("没有读到 COMPRADAR_SERPAPI_KEY")
    raise SystemExit(1)
print(f"key 长度 {len(key)}，前缀 {key[:4]}…")

queries = [
    "云南大学 信息学院 全国大学生软件测试大赛",
    "云南大学 学科竞赛 通知 2026",
]
for q in queries:
    r = requests.get(
        "https://serpapi.com/search.json",
        params={"engine": "baidu", "q": q, "num": 10, "api_key": key},
        timeout=40,
    )
    print(f"\nQ: {q}  status={r.status_code}")
    if r.status_code != 200:
        print("  错误:", r.text[:200])
        continue
    data = r.json()
    if "error" in data:
        print("  API error:", str(data["error"])[:200])
        continue
    organic = data.get("organic_results", [])
    print(f"  organic_results: {len(organic)} 条")
    ynu = 0
    for item in organic[:6]:
        link = item.get("link", "")
        if "ynu.edu.cn" in link:
            ynu += 1
        flag = "YNU" if "ynu.edu.cn" in link else "   "
        print(f"    {flag} {item.get('title','')[:58]}")
        print(f"        {link[:100]}")
    print(f"  云大命中: {ynu}")
