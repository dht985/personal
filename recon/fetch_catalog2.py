"""Dump the 立项/目录 notices to see whether the competition catalog is in the page body."""

import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from lxml import html as lxml_html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

PAGES = [
    ("http://www.jwc.ynu.edu.cn/info/1009/3988.htm", "jwc_2025_lixiang"),
    ("http://www.jwc.ynu.edu.cn/info/1009/3065.htm", "jwc_2022_lixiang"),
]

for url, name in PAGES:
    print("### " + name + "  " + url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
        r.encoding = r.apparent_encoding or "utf-8"
        (RAW / (name + ".html")).write_text(r.text, encoding="utf-8", errors="replace")
        d = lxml_html.fromstring(r.text)
        print("  title:", (d.findtext(".//title") or "").strip()[:90])
        body = " ".join((d.text_content() or "").split())
        print("  body len:", len(body))
        print("  body head:", body[:700])
        atts = d.xpath("//a[contains(@href,'.pdf') or contains(@href,'.doc') or contains(@href,'.xls') or contains(@href,'.zip') or contains(@href,'/system/')]/@href")
        for at in sorted(set(atts))[:20]:
            print("  attachment:", urljoin(r.url, at))
    except Exception as exc:
        print("  ERR:", exc)
    print()
