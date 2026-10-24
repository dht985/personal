"""查一下主流搜索 API 的当前状态与免费额度。"""

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
    ("博查 Bocha", "https://open.bochaai.com/"),
    ("Bing Web Search API", "https://www.microsoft.com/en-us/bing/apis/bing-web-search-api"),
    ("SerpApi Baidu", "https://serpapi.com/baidu-search-api"),
    ("Google CSE", "https://developers.google.com/custom-search/v1/overview"),
]

KEYWORDS = [
    "free", "免费", "quota", "额度", "pricing", "价格", "$", "retire", "retired",
    "discontinu", "deprecat", "关闭", "停止", "per 1,000", "per month", "每月",
]

for name, url in URLS:
    try:
        r = requests.get(url, headers=H, timeout=25, allow_redirects=True)
        r.encoding = r.apparent_encoding or "utf-8"
        doc = html.fromstring(r.text)
        for bad in doc.xpath("//script|//style|//noscript"):
            bad.getparent().remove(bad)
        text = " ".join((doc.text_content() or "").split())
        title = (doc.findtext(".//title") or "").strip()
        print("=" * 70)
        print(f"{name}  status={r.status_code}  final={r.url[:80]}")
        print(f"  title: {title[:70]}")
        print(f"  text len: {len(text)}")
        hits = []
        for kw in KEYWORDS:
            for m in re.finditer(re.escape(kw), text, re.I):
                seg = text[max(0, m.start() - 60): m.start() + 90]
                if seg not in hits:
                    hits.append(seg)
                break
        for seg in hits[:6]:
            print("   ·", seg[:150])
    except Exception as exc:  # noqa: BLE001
        print("=" * 70)
        print(f"{name}  ERR {type(exc).__name__}: {exc}")
