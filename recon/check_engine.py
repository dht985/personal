"""检查 canary 查询是否正常返回，以及单个赛事的定向检索结果。"""

import sys
from pathlib import Path
import urllib.parse
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from radar.config import load_config  # noqa: E402
from radar.net import Fetcher  # noqa: E402
from radar.sources import search_360  # noqa: E402
from radar.ynu_profile import engine_alive, queries_for  # noqa: E402

cfg = load_config(ROOT)
fetcher = Fetcher(cfg)

print("canary:", engine_alive(fetcher))
for q in ["云南大学", "云南大学 信息学院 全国大学生软件测试大赛",
          "云南大学 信息学院 竞赛", "云南大学 信息学院 中国人工智能大赛"]:
    hits = search_360(fetcher, q, pages=1)
    print(f"Q={q} -> {len(hits)} 条")
    for h in hits[:3]:
        print("   ", h["title"][:60])

print("\n原始响应检查：")
for q in ["云南大学", "云南大学 信息学院 竞赛"]:
    url = "https://www.so.com/s?q=" + urllib.parse.quote(q)
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}, timeout=25)
    r.encoding = r.apparent_encoding
    print(f"  {q}: status={r.status_code} len={len(r.text)} res-list={r.text.count('res-list')} "
          f"验证={('验证' in r.text)}")
