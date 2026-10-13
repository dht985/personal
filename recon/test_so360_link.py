"""Check whether so.com /link?m=... redirect pages expose the real destination."""

import re
import sys
from urllib.parse import quote_plus

import requests
from lxml import html as lxml_html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

serp = requests.get(
    f"https://www.so.com/s?q={quote_plus('云南大学 学科竞赛目录')}", headers=HEADERS, timeout=20
)
serp.encoding = serp.apparent_encoding
doc = lxml_html.fromstring(serp.text)

links = doc.xpath("//h3[contains(@class,'res-title')]/a")
print(f"results: {len(links)}")

for a in links[:3]:
    href = a.get("href") or ""
    title = " ".join((a.text_content() or "").split())
    print(f"\n--- {title[:70]}\n    {href[:120]}")
    if "so.com/link" not in href:
        print("    (direct)")
        continue
    r = requests.get(href, headers=HEADERS, timeout=20, allow_redirects=True)
    print(f"    status={r.status_code} final={r.url[:120]}")
    print(f"    len={len(r.text)}")
    for pat in [r'https?://[^\s"\'<>]{10,120}']:
        found = [u for u in re.findall(pat, r.text) if "so.com" not in u][:6]
        for u in found:
            print("    url-in-body:", u)
    for m in re.findall(r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]*>', r.text, re.I):
        print("    meta-refresh:", m[:150])
    for m in re.findall(r'(?:location\.(?:replace|href)\s*=\s*|window\.open\()["\']([^"\']+)', r.text):
        print("    js-redirect:", m[:150])

# try a Bing site-restricted query as an alternative discovery channel
print("\n\n=== bing site: query")
q = "site:jwc.ynu.edu.cn 竞赛"
r = requests.get(
    "https://cn.bing.com/search", params={"q": q, "setlang": "zh-CN"}, headers=HEADERS, timeout=20
)
r.encoding = r.apparent_encoding
doc = lxml_html.fromstring(r.text)
for li in doc.xpath("//li[contains(@class,'b_algo')]")[:8]:
    a = li.xpath(".//h2/a")
    if a:
        print("  *", " ".join((a[0].text_content() or "").split())[:70], "|", (a[0].get("href") or "")[:100])
