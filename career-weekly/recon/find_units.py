"""定位 211 所与南网数字的官网域名。"""

import re
import sys
import urllib.parse

import requests
from lxml import html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def sogou(q):
    r = requests.get("https://www.sogou.com/web?query=" + urllib.parse.quote(q), headers=H, timeout=20)
    r.encoding = r.apparent_encoding or "utf-8"
    doc = html.fromstring(r.text)
    print(f"\n=== 搜狗: {q}")
    for a in doc.xpath("//h3/a")[:5]:
        title = " ".join((a.text_content() or "").split())[:50]
        href = a.get("href") or ""
        real = ""
        if href.startswith("/link"):
            try:
                rr = requests.get("https://www.sogou.com" + href, headers=H, timeout=15)
                rr.encoding = rr.apparent_encoding or "utf-8"
                urls = [
                    u for u in re.findall(r"https?://[^\s'\"<>]{8,120}", rr.text)
                    if "sogou" not in u and "sogoucdn" not in u
                ]
                real = urls[0] if urls else ""
            except Exception as exc:  # noqa: BLE001
                real = f"ERR {type(exc).__name__}"
        print(f"  {title}")
        print(f"    {real or href[:90]}")


def bing(q):
    r = requests.get(
        "https://www.bing.com/search",
        params={"q": q, "mkt": "zh-CN", "setlang": "zh-Hans"},
        headers=H,
        timeout=20,
    )
    r.encoding = r.apparent_encoding or "utf-8"
    doc = html.fromstring(r.text)
    print(f"\n=== Bing: {q}")
    for li in doc.xpath("//li[contains(@class,'b_algo')]")[:5]:
        a = li.xpath(".//h2/a")
        if a:
            print(f"  {' '.join((a[0].text_content() or '').split())[:50]}")
            print(f"    {(a[0].get('href') or '')[:100]}")


for q in ["昆明物理研究所 官网", "中国兵器工业 昆明物理研究所", "南方电网数字电网集团 官网"]:
    sogou(q)
    bing(q)

print("\n=== 兵器工业集团首页找昆明相关链接 ===")
r = requests.get("http://www.norincogroup.com.cn/", headers=H, timeout=20)
r.encoding = r.apparent_encoding or "utf-8"
doc = html.fromstring(r.text)
for a in doc.xpath("//a[@href]"):
    t = " ".join((a.text_content() or "").split())
    if any(k in t for k in ("昆明", "物理", "211", "成员", "单位")):
        print(f"  {t[:40]:<42} {a.get('href')[:80]}")
