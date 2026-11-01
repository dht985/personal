"""Playwright 渲染：给 JS 页面和强反爬站点兜底。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from playwright.sync_api import sync_playwright


def render_many(
    urls: list[str], raw_dir: Path, timeout: int = 45000, wait_ms: int = 2500
) -> dict[str, str]:
    """复用同一个浏览器实例渲染多个页面，比逐页启动更稳、更快。"""
    out: dict[str, str] = {}
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            for url in urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                    page.wait_for_timeout(wait_ms)
                    out[url] = page.content()
                except Exception:  # noqa: BLE001
                    out[url] = ""
            browser.close()
    except Exception:  # noqa: BLE001
        return {u: out.get(u, "") for u in urls}
    for url, html in out.items():
        if not html:
            continue
        key = hashlib.sha1(url.encode("utf-8")).hexdigest()
        (raw_dir / f"{key}.rendered.html").write_text(html, encoding="utf-8", errors="replace")
    return out


def render(url: str, raw_dir: Path, timeout: int = 45000, wait_ms: int = 2500) -> str:
    return render_many([url], raw_dir, timeout, wait_ms).get(url, "")
