"""Fetch the YNU competition column and the catalog notices, dump readable text."""

import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from lxml import html as lxml_html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def get(url, name):
    r = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
    r.encoding = r.apparent_encoding or "utf-8"
    (RAW / (name + ".html")).write_text(r.text, encoding="utf-8", errors="replace")
    return r


LIST_URL = "http://www.jwc.ynu.edu.cn/zysw/xkjs_.htm"
print("### list page " + LIST_URL)
r = get(LIST_URL, "jwc_xkjs_list")
print("  status", r.status_code, "len", len(r.text), "final", r.url)
doc = lxml_html.fromstring(r.text)
items = doc.xpath("//a[contains(@href,'/info/')]")
print("  item links:", len(items))
for a in items[:40]:
    txt = " ".join((a.text_content() or "").split())
    if txt:
        print("   ", txt[:58].ljust(60), urljoin(r.url, a.get("href")))

pager = doc.xpath("//a[contains(@href,'xkjs_')]/@href")
print("  pager:", sorted(set(p for p in pager if p != "xkjs_.htm"))[:10])
