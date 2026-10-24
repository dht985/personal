"""探测：针对云南大学的名誉/导师/获奖搜索，360 和 Bing 各能返回什么。"""

import sys
import urllib.parse
from pathlib import Path

import requests
from lxml import html

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from radar.config import load_config  # noqa: E402
from radar.net import Fetcher  # noqa: E402
from radar.sources import resolve_redirect  # noqa: E402

SEP = "=" * 70
H = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def so360(q: str):
    r = requests.get("https://www.so.com/s?q=" + urllib.parse.quote(q), headers=H, timeout=25)
    r.encoding = r.apparent_encoding
    doc = html.fromstring(r.text)
    out = []
    for li in doc.xpath("//li[contains(@class,'res-list')]"):
        a = li.xpath(".//h3[contains(@class,'res-title')]/a")
        if not a:
            continue
        desc = li.xpath(".//*[contains(@class,'res-desc') or contains(@class,'res-richtext')]")
        out.append((
            " ".join((a[0].text_content() or "").split())[:70],
            a[0].get("href") or "",
            " ".join((desc[0].text_content() or "").split())[:90] if desc else "",
        ))
    return out[:6]


def bing(q: str):
    r = requests.get(
        "https://cn.bing.com/search",
        params={"q": q, "setlang": "zh-CN"},
        headers=H,
        timeout=25,
    )
    r.encoding = r.apparent_encoding
    doc = html.fromstring(r.text)
    out = []
    for li in doc.xpath("//li[contains(@class,'b_algo')]"):
        a = li.xpath(".//h2/a")
        if not a:
            continue
        out.append((
            " ".join((a[0].text_content() or "").split())[:70],
            a[0].get("href") or "",
            " ".join((li.text_content() or "").split())[:90],
        ))
    return out[:6]


def main() -> int:
    cfg = load_config(ROOT)
    fetcher = Fetcher(cfg, offline=False)
    name = sys.argv[1] if len(sys.argv) > 1 else "全国大学生软件测试大赛"
    queries = [
        f"云南大学 {name}",
        f"云南大学 信息学院 {name}",
        f"云南大学 {name} 获奖",
        f"云南大学 {name} 指导教师",
        f"site:ynu.edu.cn {name}",
    ]
    for q in queries:
        print(SEP)
        print("Q: " + q)
        for engine, fn in (("360", so360), ("bing", bing)):
            try:
                hits = fn(q)
            except Exception as exc:  # noqa: BLE001
                print(f"  [{engine}] ERR {type(exc).__name__}")
                continue
            print(f"  [{engine}] {len(hits)} 条")
            for title, href, snippet in hits[:4]:
                real = resolve_redirect(fetcher, href) if "so.com/link" in href else href
                flag = "YNU" if "ynu.edu.cn" in real else "   "
                print(f"    {flag} {title}")
                print(f"        {real[:100]}")
                if snippet:
                    print(f"        {snippet[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
