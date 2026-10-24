"""在 360 被限流时，试搜狗和必应能不能顶上。"""

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
    "Accept": "text/html,application/xhtml+xml",
}

Q = "云南大学 信息学院 全国大学生软件测试大赛"


def probe(name, url, selectors):
    try:
        r = requests.get(url, headers=H, timeout=25, allow_redirects=True)
        r.encoding = r.apparent_encoding
        doc = html.fromstring(r.text)
        print(f"\n== {name}: status={r.status_code} len={len(r.text)} final={r.url[:80]}")
        for sel in selectors:
            nodes = doc.xpath(sel)
            print(f"   {sel} -> {len(nodes)}")
            for node in nodes[:5]:
                if isinstance(node, str):
                    continue
                text = " ".join((node.text_content() or "").split())[:70]
                if text:
                    print(f"       {text}")
        title = doc.findtext(".//title") or ""
        print("   title:", title.strip()[:60])
        print("   含'验证':", "验证" in r.text, "| 含'安全':", "安全" in r.text)
    except Exception as exc:  # noqa: BLE001
        print(f"\n== {name}: ERR {type(exc).__name__} {exc}")


probe(
    "sogou",
    "https://www.sogou.com/web?query=" + urllib.parse.quote(Q),
    ["//div[contains(@class,'vrwrap')]", "//h3/a", "//div[contains(@class,'results')]"],
)
probe(
    "bing-mkt",
    "https://www.bing.com/search?q=" + urllib.parse.quote(Q) + "&mkt=zh-CN&setlang=zh-Hans",
    ["//li[contains(@class,'b_algo')]", "//h2/a"],
)
probe(
    "so360",
    "https://www.so.com/s?q=" + urllib.parse.quote(Q),
    ["//li[contains(@class,'res-list')]"],
)

print("\n== 搜狗结果链接形态 ==")
r = requests.get("https://www.sogou.com/web?query=" + urllib.parse.quote(Q), headers=H, timeout=25)
r.encoding = r.apparent_encoding
doc = html.fromstring(r.text)
for a in doc.xpath("//h3/a")[:5]:
    print("  ", (a.get("href") or "")[:110])
    print("     ", " ".join((a.text_content() or "").split())[:60])

first = doc.xpath("//h3/a")[0].get("href")
if first.startswith("/"):
    rr = requests.get("https://www.sogou.com" + first, headers=H, timeout=25, allow_redirects=True)
    print("\n解析第一条 ->", rr.status_code, rr.url[:120])
