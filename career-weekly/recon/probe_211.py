"""定位 211 所的可抓来源。"""

import sys
import urllib.parse

import requests
from lxml import html
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    for url in ["http://jobs.ynu.edu.cn/", "https://jobs.ynu.edu.cn/company/view/id/490636"]:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=40000)
            page.wait_for_timeout(3000)
            text = page.inner_text("body")
            print(f"\n=== {url}  title={page.title()[:40]} text={len(text)}")
            print(" ", " ".join(text.split())[:300])
            links = page.eval_on_selector_all("a", "els => els.map(e => [e.innerText.trim(), e.href]).filter(x => x[0])")
            for t, h in links[:15]:
                print(f"   {t[:40]:<42} {h[:80]}")
        except Exception as exc:  # noqa: BLE001
            print(f"\n=== {url} ERR {type(exc).__name__}")
    browser.close()

print("\n=== 搜狗：昆明北方红外 官网 ===")
r = requests.get("https://www.sogou.com/web?query=" + urllib.parse.quote("昆明北方红外技术股份有限公司 官网"), headers=H, timeout=20)
r.encoding = r.apparent_encoding or "utf-8"
doc = html.fromstring(r.text)
for a in doc.xpath("//h3/a")[:5]:
    print("  ", " ".join((a.text_content() or "").split())[:50], "|", (a.get("href") or "")[:90])
