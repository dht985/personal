"""打印 SerpApi 价格页的方案与额度，以及它支持哪些引擎。"""

import re
import sys

import requests
from lxml import html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

r = requests.get("https://serpapi.com/pricing", headers=H, timeout=25)
r.encoding = r.apparent_encoding or "utf-8"
doc = html.fromstring(r.text)
for bad in doc.xpath("//script|//style"):
    bad.getparent().remove(bad)
text = " ".join((doc.text_content() or "").split())

print("=== 含 plan/Free 的片段 ===")
for kw in ["Free", "免费", "searches per month", "searches/month"]:
    for m in list(re.finditer(re.escape(kw), text, re.I))[:4]:
        print("·", text[max(0, m.start() - 90): m.start() + 110][:200])
    print()

print("=== 引擎列表页 ===")
r2 = requests.get("https://serpapi.com/search-api", headers=H, timeout=25)
r2.encoding = r2.apparent_encoding or "utf-8"
text2 = " ".join((html.fromstring(r2.text).text_content() or "").split())
for name in ["Baidu", "Sogou", "Bing", "Google", "360"]:
    print(f"  {name}: {'出现' if name.lower() in text2.lower() else '未出现'}")
