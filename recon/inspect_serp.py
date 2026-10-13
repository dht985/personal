"""Inspect saved search-result pages to figure out the right CSS/XPath selectors."""

import re
import sys
from pathlib import Path

from lxml import html as lxml_html

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

CANDIDATES = {
    "search_bing.html": [
        "//li[contains(@class,'b_algo')]",
        "//h2/a",
        "//ol[@id='b_results']/li",
    ],
    "search_so360.html": [
        "//li[contains(@class,'res-list')]",
        "//h3[contains(@class,'res-title')]/a",
        "//div[@class='result']",
    ],
    "search_ddg_html.html": [
        "//div[contains(@class,'result')]",
        "//a[contains(@class,'result__a')]",
    ],
}

for fname, xpaths in CANDIDATES.items():
    p = RAW / fname
    print(f"########## {fname}  exists={p.exists()}")
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8", errors="replace")
    print("bytes:", len(text))
    for marker in ["b_algo", "b_results", "res-list", "res-title", "captcha", "verify",
                   "验证", "result__a", "anomaly", "challenge"]:
        n = text.count(marker)
        if n:
            print(f"   marker {marker!r}: {n}")
    doc = lxml_html.fromstring(text)
    for xp in xpaths:
        nodes = doc.xpath(xp)
        print(f"   xpath {xp} -> {len(nodes)}")
        for n in nodes[:5]:
            if isinstance(n, str):
                print("        str:", n[:100])
                continue
            href = n.get("href") if n.get("href") else ""
            t = " ".join((n.text_content() or "").split())[:90]
            print(f"        {t}  |  {href[:110]}")
    print()
