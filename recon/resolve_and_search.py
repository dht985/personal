"""Resolve 360 search redirect links and run a few decisive discovery queries."""

import json
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from lxml import html as lxml_html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def so360(query, tag):
    url = f"https://www.so.com/s?q={quote_plus(query)}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.encoding = r.apparent_encoding or "utf-8"
    (RAW / f"so360_{tag}.html").write_text(r.text, encoding="utf-8", errors="replace")
    doc = lxml_html.fromstring(r.text)
    out = []
    for a in doc.xpath("//h3[contains(@class,'res-title')]/a"):
        out.append({"title": " ".join((a.text_content() or "").split())[:95],
                    "href": a.get("href") or ""})
    return out


def resolve(url):
    if "so.com/link" not in url:
        return url, None
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        return r.url, r.status_code
    except Exception as exc:  # noqa: BLE001
        return f"ERR {type(exc).__name__}", None


def run_searches():
    queries = [
        ("云南大学 学科竞赛目录 认定", "catalog"),
        ("云南大学 本科生院 学科竞赛", "bksy"),
        ("云南大学 综合素质测评 实施办法 竞赛 加分", "zhice"),
        ("云南大学 本科生院 竞赛 通知", "notice"),
    ]
    result = {}
    for q, tag in queries:
        try:
            items = so360(q, tag)
        except Exception as exc:  # noqa: BLE001
            items = [{"title": f"ERR {exc}", "href": ""}]
        print(f"\n===== {q}")
        for it in items[:6]:
            final, code = resolve(it["href"])
            it["final_url"] = final
            print(f"  [{code}] {it['title']}")
            print(f"        {final}")
        result[q] = items
        time.sleep(1)
    (ROOT / "data" / "search_probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def resolve_previous():
    p = RAW / "search_so360.html"
    if not p.exists():
        return
    doc = lxml_html.fromstring(p.read_text(encoding="utf-8", errors="replace"))
    print("\n===== resolve earlier so.com hits")
    for a in doc.xpath("//h3[contains(@class,'res-title')]/a")[:6]:
        final, code = resolve(a.get("href") or "")
        print(f"  [{code}] {urljoin('', final)}")


if __name__ == "__main__":
    resolve_previous()
    run_searches()
