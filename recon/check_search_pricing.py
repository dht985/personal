"""查博查与 SerpApi 的定价/免费额度。"""

import re
import sys

import requests
from lxml import html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

URLS = [
    ("博查-首页", "https://open.bochaai.com/"),
    ("博查-价格", "https://open.bochaai.com/pricing"),
    ("博查-文档", "https://open.bochaai.com/docs"),
    ("SerpApi-价格", "https://serpapi.com/pricing"),
]

for name, url in URLS:
    try:
        r = requests.get(url, headers=H, timeout=25, allow_redirects=True)
        r.encoding = r.apparent_encoding or "utf-8"
        doc = html.fromstring(r.text)
        for bad in doc.xpath("//script|//style|//noscript"):
            bad.getparent().remove(bad)
        text = " ".join((doc.text_content() or "").split())
        print("=" * 70)
        print(f"{name} status={r.status_code} len={len(text)} final={r.url[:70]}")
        # 抓和钱/额度有关的句子
        for kw in ["免费", "元", "次", "额度", "价格", "free", "search", "month", "$"]:
            idx = text.find(kw)
            if idx >= 0:
                print(f"   [{kw}] ...{text[max(0, idx-70): idx+110]}...")
    except Exception as exc:  # noqa: BLE001
        print("=" * 70)
        print(f"{name} ERR {type(exc).__name__}: {exc}")
