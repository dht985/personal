"""Reconnaissance probe: which sources are reachable and parseable as plain HTML."""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import requests
from lxml import html as lxml_html

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

KEYWORDS = ["竞赛", "认定", "测评", "大赛", "创新创业", "实践"]


def probe(name, url, save=True):
    info = {"name": name, "url": url}
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        info["status"] = r.status_code
        info["final_url"] = r.url
        info["encoding"] = r.encoding
        if r.encoding is None or r.encoding.lower() in ("iso-8859-1",):
            r.encoding = r.apparent_encoding
        info["bytes"] = len(r.content)
        info["len_text"] = len(r.text)
        if save:
            fn = re.sub(r"[^0-9A-Za-z_.-]", "_", name) + ".html"
            (RAW / fn).write_text(r.text, encoding="utf-8", errors="replace")
            info["saved"] = fn
        try:
            doc = lxml_html.fromstring(r.text)
            info["title"] = (doc.findtext(".//title") or "").strip()[:120]
            links = doc.xpath("//a/@href")
            info["n_links"] = len(links)
            hits = []
            for a in doc.xpath("//a"):
                txt = " ".join((a.text_content() or "").split())
                if any(k in txt for k in KEYWORDS):
                    hits.append({"text": txt[:80], "href": urljoin(r.url, a.get("href") or "")})
                if len(hits) >= 12:
                    break
            info["kw_links"] = hits
            body = " ".join((doc.text_content() or "").split())
            info["body_head"] = body[:200]
        except Exception as exc:  # noqa: BLE001
            info["parse_error"] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def probe_search(engine_name, template, query):
    url = template.format(q=quote_plus(query))
    info = probe(f"search_{engine_name}", url, save=True)
    info["query"] = query
    return info


def main():
    tasks = [
        ("ynu_jwc_home", "https://jwc.ynu.edu.cn/"),
        ("ynu_home", "https://www.ynu.edu.cn/"),
        ("ynu_cs_college", "http://www.sei.ynu.edu.cn/"),
        ("cahe_home", "https://www.cahe.edu.cn/"),
        ("mooc_cy", "https://www.cyol.com/"),
    ]
    results = []
    for name, url in tasks:
        results.append(probe(name, url))
        time.sleep(1)

    q = "云南大学 学科竞赛 认定 目录"
    searches = [
        ("bing", "https://cn.bing.com/search?q={q}&setlang=zh-CN"),
        ("baidu", "https://www.baidu.com/s?wd={q}"),
        ("ddg_html", "https://html.duckduckgo.com/html/?q={q}"),
        ("so360", "https://www.so.com/s?q={q}"),
    ]
    for eng, tpl in searches:
        results.append(probe_search(eng, tpl, q))
        time.sleep(1)

    out = ROOT / "data" / "recon_report.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in results:
        print(
            f"[{r.get('status', 'ERR')}] {r['name']:<18} "
            f"bytes={r.get('bytes', '-')} links={r.get('n_links', '-')} "
            f"title={(r.get('title') or r.get('error') or r.get('parse_error') or '')[:70]}"
        )
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    sys.exit(main())
