from __future__ import annotations

import re

from lxml import html as lxml_html

CONTENT_XPATHS = [
    "//div[contains(@class,'article')]",
    "//div[contains(@class,'content')]",
    "//div[@id='content']",
    "//div[contains(@class,'detail')]",
    "//article",
    "//main",
]


def main_text(raw: str, limit: int = 2500) -> str:
    """从详情页提取正文，失败则回退到全页文本。"""
    try:
        doc = lxml_html.fromstring(raw)
    except Exception:  # noqa: BLE001
        return ""
    for bad in doc.xpath("//script|//style|//noscript|//nav|//footer|//header"):
        bad.getparent().remove(bad)

    best = ""
    for xp in CONTENT_XPATHS:
        for node in doc.xpath(xp):
            text = " ".join((node.text_content() or "").split())
            if len(text) > len(best):
                best = text
    if len(best) < 120:
        best = " ".join((doc.text_content() or "").split())
    return best[:limit]


def extract_dates(text: str) -> list[str]:
    return re.findall(r"20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}", text or "")
