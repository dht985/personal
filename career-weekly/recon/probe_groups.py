"""批量探测军工/能源央企官网可抓性。"""

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

GROUPS = [
    ("国家电网", "http://www.sgcc.com.cn/"),
    ("中国华能", "https://www.chng.com.cn/"),
    ("中国大唐", "https://www.china-cdt.com/"),
    ("中国华电", "https://www.chd.com.cn/"),
    ("国家电投", "https://www.spic.com.cn/"),
    ("中国三峡", "https://www.ctg.com.cn/"),
    ("中广核", "https://www.cgnpc.com.cn/"),
    ("中国石油", "https://www.cnpc.com.cn/"),
    ("中国石化", "http://www.sinopecgroup.com/"),
    ("中国海油", "https://www.cnooc.com.cn/"),
    ("国家管网", "https://www.pipechina.com.cn/"),
    ("中国中煤", "https://www.chinacoal.com/"),
    ("中国电建", "https://www.powerchina.cn/"),
    ("中国能建", "https://www.ceec.net.cn/"),
    ("航天科技", "https://www.spacechina.com/"),
    ("航天科工", "https://www.casic.com.cn/"),
    ("航空工业", "https://www.avic.com/"),
    ("中国船舶", "https://www.cssc.net.cn/"),
    ("兵器装备", "https://www.csgc.com.cn/"),
    ("中国电子", "https://www.cec.com.cn/"),
    ("中国航发", "https://www.aecc.cn/"),
]

for name, url in GROUPS:
    try:
        r = requests.get(url, headers=H, timeout=18, allow_redirects=True)
        r.encoding = r.apparent_encoding or "utf-8"
        doc = html.fromstring(r.text)
        for bad in doc.xpath("//script|//style|//noscript"):
            bad.getparent().remove(bad)
        text = " ".join((doc.text_content() or "").split())
        title = (doc.findtext(".//title") or "").strip()
        news = [
            a for a in doc.xpath("//a[@href]")
            if any(k in (a.text_content() or "") for k in ("招聘", "校园", "公告", "新闻", "会议", "招标"))
        ]
        print(f"[{r.status_code}] {name:<8} text={len(text):<6} news={len(news):<3} {title[:28]}")
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] {name:<8} {type(exc).__name__}")
    time.sleep(0.8)
