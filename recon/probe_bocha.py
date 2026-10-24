"""用真实浏览器打开博查开放平台，看定价与能力说明。"""

import sys

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto("https://open.bochaai.com/", wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(1500)
    text = page.inner_text("body")
    print("=== 首页正文 ===")
    print(text[:2500])
    print("\n=== 导航链接 ===")
    for a in page.query_selector_all("a"):
        label = (a.inner_text() or "").strip()
        href = a.get_attribute("href") or ""
        if label and href:
            print(f"  {label[:30]:<32} {href[:70]}")
    browser.close()
