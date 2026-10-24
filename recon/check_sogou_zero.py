"""搜狗对某些查询返回 0 条时，到底是"真没有"还是被拦了。"""

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

for q in ["云南大学 学科竞赛 通知 2026", "中国高校计算机大赛 2026",
          "云南大学 信息学院 全国大学生软件测试大赛"]:
    url = "https://www.sogou.com/web?query=" + urllib.parse.quote(q)
    r = requests.get(url, headers=H, timeout=25, allow_redirects=True)
    r.encoding = r.apparent_encoding
    doc = html.fromstring(r.text)
    title = (doc.findtext(".//title") or "").strip()
    print(f"\nQ={q}")
    print(f"  status={r.status_code} len={len(r.text)} final={r.url[:70]}")
    print(f"  title={title[:50]}")
    wrappers = doc.xpath("//div[contains(@class,'vrwrap')]")
    h3s = doc.xpath("//h3/a")
    print(f"  vrwrap={len(wrappers)} h3a={len(h3s)}")
    for kw in ("验证", "安全验证", "机器人", "频繁", "无结果", "没有找到"):
        if kw in r.text:
            print(f"  含关键词: {kw}")
