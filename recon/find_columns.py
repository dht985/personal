"""Find list-page URLs for the columns that publish competition notices."""

import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from lxml import html as lxml_html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
    r.encoding = r.apparent_encoding or "utf-8"
    return r


def listy_links(base_url, text, limit=40):
    doc = lxml_html.fromstring(text)
    seen = []
    for a in doc.xpath("//a"):
        href = a.get("href") or ""
        txt = " ".join((a.text_content() or "").split())
        if not href or href.startswith(("#", "javascript")):
            continue
        full = urljoin(base_url, href)
        if "__" in href or "/info/" in href:
            continue
        seen.append((txt[:34], full))
    out = []
    for t, u in seen:
        if u not in [x[1] for x in out]:
            out.append((t, u))
    return out[:limit]


print("### jwc.ynu.edu.cn column candidates")
r = fetch("https://jwc.ynu.edu.cn/")
for t, u in listy_links(r.url, r.text, 60):
    if any(k in t for k in ("通知", "竞赛", "公告", "实践", "创新", "列表")) or "list" in u or "tz" in u:
        print(f"   {t:<36} {u}")

print("\n### sjjx.ynu.edu.cn 学科竞赛管理系统")
try:
    r2 = fetch("https://sjjx.ynu.edu.cn/xkjs/XKJS/YNU")
    doc = lxml_html.fromstring(r2.text)
    print("   status", r2.status_code, "title", (doc.findtext(".//title") or "").strip()[:60])
    body = " ".join((doc.text_content() or "").split())
    print("   body:", body[:300])
except Exception as exc:  # noqa: BLE001
    print("   ERR", exc)

print("\n### cahe.edu.cn 竞赛工作 term/906")
try:
    r3 = fetch("https://www.cahe.edu.cn/site/term/906.html")
    doc = lxml_html.fromstring(r3.text)
    print("   status", r3.status_code, "title", (doc.findtext(".//title") or "").strip()[:60])
    for a in doc.xpath("//a")[:25]:
        txt = " ".join((a.text_content() or "").split())
        href = a.get("href") or ""
        if txt and ("竞赛" in txt or "content" in href):
            print(f"   {txt[:50]:<52} {urljoin(r3.url, href)}")
except Exception as exc:  # noqa: BLE001
    print("   ERR", exc)
