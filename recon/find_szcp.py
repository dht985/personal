"""尝试定位云南大学现行本科生综合素质测评办法原文。"""

import re
import sys
import urllib.parse
from pathlib import Path

import requests
from lxml import html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]

H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def so360(query: str) -> list[tuple[str, str]]:
    r = requests.get("https://www.so.com/s?q=" + urllib.parse.quote(query), headers=H, timeout=20)
    r.encoding = r.apparent_encoding
    doc = html.fromstring(r.text)
    out = []
    for a in doc.xpath("//h3[contains(@class,'res-title')]/a")[:7]:
        title = " ".join((a.text_content() or "").split())[:70]
        out.append((title, a.get("href") or ""))
    return out


def resolve(url: str) -> str:
    if "so.com/link" not in url:
        return url
    try:
        r = requests.get(url, headers=H, timeout=15)
        m = re.search(r"URL='([^']+)'", r.text)
        return m.group(1) if m else url
    except Exception:  # noqa: BLE001
        return url


if __name__ == "__main__":
    queries = [
        "云南大学 本科生 综合素质测评 实施办法",
        "云南大学 学生综合素质测评办法 竞赛 加分 德育",
        "云南大学 学生工作部 综合素质测评 文件",
        "云南大学软件学院 学生综合素质测评实施细则",
        "云南大学 信息学院 综合素质测评 实施细则 竞赛 加分",
    ]
    for q in queries:
        print("==", q)
        try:
            for title, href in so360(q):
                print("   ", title)
                print("        ", resolve(href)[:120])
        except Exception as exc:  # noqa: BLE001
            print("   ERR", exc)
