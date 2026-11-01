"""用 Playwright 渲染反爬/JS 页面，看能否拿到内容。"""

import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URLS = [
    ("南网数研院资讯", "https://nwsyy.csg.cn/zx/"),
    ("云大就业网-211所", "http://jobs.ynu.edu.cn/company/view/id/490636"),
    ("国家电网", "http://www.sgcc.com.cn/"),
    ("中国石油", "https://www.cnpc.com.cn/"),
    ("中国海油", "https://www.cnooc.com.cn/"),
    ("航天科技", "https://www.spacechina.com/"),
    ("航天科工", "https://www.casic.com.cn/"),
    ("中国船舶", "https://www.cssc.net.cn/"),
]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    for name, url in URLS:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            title = page.title()
            text = page.inner_text("body")
            links = page.eval_on_selector_all("a", "els => els.length")
            print(f"\n=== {name}  {url}")
            print(f"  title={title[:60]}")
            print(f"  text={len(text)} links={links}")
            print("  head:", " ".join(text.split())[:200])
        except Exception as exc:  # noqa: BLE001
            print(f"\n=== {name}  ERR {type(exc).__name__}: {str(exc)[:80]}")
    browser.close()
