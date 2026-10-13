"""Locate the real hostname of 云南大学本科生院 (the office that manages 学科竞赛)."""

import re
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


def links_from_saved(fname, pattern):
    p = RAW / fname
    if not p.exists():
        print(f"(missing {fname})")
        return
    text = p.read_text(encoding="utf-8", errors="replace")
    doc = lxml_html.fromstring(text)
    seen = set()
    for a in doc.xpath("//a"):
        txt = " ".join((a.text_content() or "").split())
        href = a.get("href") or ""
        if re.search(pattern, txt) or re.search(pattern, href):
            full = urljoin("https://www.ynu.edu.cn/", href)
            if full in seen:
                continue
            seen.add(full)
            print(f"   {txt[:40]:<42} -> {full}")
    print()


def try_hosts(hosts):
    for h in hosts:
        for scheme in ("https", "http"):
            url = f"{scheme}://{h}/"
            try:
                r = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
                r.encoding = r.apparent_encoding or "utf-8"
                doc = lxml_html.fromstring(r.text)
                title = (doc.findtext(".//title") or "").strip()
                print(f"[{r.status_code}] {url}  -> {r.url}  {title[:60]}")
                if r.status_code == 200 and title:
                    return r.url
            except Exception as exc:  # noqa: BLE001
                print(f"[ERR] {url}  {type(exc).__name__}")
    return None


if __name__ == "__main__":
    print("=== links mentioning 本科生院 in ynu_home.html")
    links_from_saved("ynu_home.html", r"本科生院")
    print("=== links mentioning 本科生院/学科竞赛 in ynu_jwc_home.html")
    links_from_saved("ynu_jwc_home.html", r"本科生院|学科竞赛")

    print("=== probing candidate hostnames")
    hit = try_hosts(
        [
            "bksy.ynu.edu.cn",
            "undergraduate.ynu.edu.cn",
            "bkjx.ynu.edu.cn",
            "jwc.ynu.edu.cn",
        ]
    )
