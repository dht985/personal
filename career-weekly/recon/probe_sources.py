"""探测目标单位官网的可抓取性与列表结构。"""

import sys
import time

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

URLS = [
    ("中国电科", "https://www.cetc.com.cn/"),
    ("54所(cti)", "http://www.cti.ac.cn/"),
    ("兵器工业集团", "http://www.norincogroup.com.cn/"),
    ("南方电网", "https://www.csg.cn/"),
    ("南网数字", "https://digital.csg.cn/"),
    ("国家能源集团", "https://www.ceic.com/"),
    ("中核集团", "https://www.cnnc.com.cn/"),
    ("国资委央企名录", "http://www.sasac.gov.cn/"),
]

for name, url in URLS:
    try:
        r = requests.get(url, headers=H, timeout=20, allow_redirects=True)
        r.encoding = r.apparent_encoding or "utf-8"
        doc = html.fromstring(r.text)
        for bad in doc.xpath("//script|//style|//noscript"):
            bad.getparent().remove(bad)
        text = " ".join((doc.text_content() or "").split())
        title = (doc.findtext(".//title") or "").strip()
        links = doc.xpath("//a[@href]")
        newsish = [
            a for a in links
            if any(k in (a.text_content() or "") for k in ("招聘", "校园", "公告", "新闻", "会议", "招标"))
        ]
        print(f"\n=== {name}  status={r.status_code}  final={r.url[:60]}")
        print(f"  title: {title[:50]}")
        print(f"  text={len(text)}  links={len(links)}  newsish={len(newsish)}")
        for a in newsish[:5]:
            t = " ".join((a.text_content() or "").split())[:40]
            print(f"    {t:<42} {a.get('href')[:70]}")
    except Exception as exc:  # noqa: BLE001
        print(f"\n=== {name}  ERR {type(exc).__name__}: {str(exc)[:80]}")
    time.sleep(1.2)
