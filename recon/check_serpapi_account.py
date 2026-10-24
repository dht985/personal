"""查看 SerpApi 账号额度与最近一小时用量。"""

import os
import sys

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

key = (os.environ.get("COMPRADAR_SERPAPI_KEY") or "").strip()
if not key:
    print("没有 key")
    raise SystemExit(1)
r = requests.get("https://serpapi.com/account", params={"api_key": key}, timeout=30)
print("status", r.status_code)
if r.status_code == 200:
    d = r.json()
    for k in ("plan_name", "searches_per_month", "plan_searches_left",
              "this_month_usage", "last_hour_searches", "throughput_per_hour",
              "account_email", "renewal_date"):
        if k in d:
            print(f"  {k}: {d[k]}")
else:
    print(r.text[:300])
