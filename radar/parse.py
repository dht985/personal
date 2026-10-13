"""网页解析：列表页 -> 通知条目；详情页 -> 正文、发布时间、外链、附件。"""

from __future__ import annotations

import datetime as _dt
import re
from urllib.parse import urljoin, urlsplit

from lxml import html as lxml_html

from .textutil import clean_text

DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")


def _iso_from_match(m: re.Match) -> str | None:
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except (ValueError, TypeError):
        return None


def parse_list_page(raw_html: str, base_url: str, item_regex: str) -> list[dict]:
    """从栏目列表页提取通知条目（标题 + 链接 + 列表页上的日期线索）。"""
    doc = lxml_html.fromstring(raw_html)
    pattern = re.compile(item_regex)
    items: list[dict] = []
    seen: set[str] = set()
    for a in doc.xpath("//a[@href]"):
        href = a.get("href") or ""
        full = urljoin(base_url, href).split("#")[0]
        # 列表页里的链接往往是相对路径（info/1009/xxx.htm），必须用绝对地址做匹配
        if not pattern.search(full):
            continue
        if full in seen:
            continue
        seen.add(full)
        title = clean_text(a.text_content() or "") or clean_text(a.get("title") or "")
        parent = a.getparent()
        parent_text = ""
        for _ in range(3):
            if parent is None:
                break
            parent_text = clean_text(parent.text_content() or "")
            if DATE_RE.search(parent_text):
                break
            parent = parent.getparent()
        m = DATE_RE.search(parent_text or "")
        items.append(
            {
                "title": title,
                "url": full,
                "list_date": _iso_from_match(m) if m else None,
            }
        )
    return items


_CONTENT_XPATHS = [
    "//div[@id='vsb_content']",
    "//div[contains(@class,'v_news_content')]",
    "//div[contains(@class,'content')]",
    "//div[@id='content']",
    "//article",
]


def parse_detail_page(
    raw_html: str,
    url: str,
    own_hosts: set[str] | None = None,
    link_filter: dict | None = None,
) -> dict:
    """解析通知详情页。"""
    own_suffixes = (link_filter or {}).get("own_suffixes", [])
    blacklist = set((link_filter or {}).get("blacklist_hosts", []))
    doc = lxml_html.fromstring(raw_html)
    for bad in doc.xpath("//script|//style|//noscript"):
        bad.getparent().remove(bad)

    title = clean_text(doc.findtext(".//title") or "")
    if "-" in title:
        head = title.split("-")[0].strip()
        if len(head) >= 6:
            title = head

    body_el = None
    for xp in _CONTENT_XPATHS:
        nodes = doc.xpath(xp)
        if nodes:
            candidate = max(nodes, key=lambda n: len(n.text_content() or ""))
            if body_el is None or len(candidate.text_content() or "") > len(body_el.text_content() or ""):
                body_el = candidate
            if len(clean_text(candidate.text_content() or "")) > 80:
                break

    full_text = clean_text(doc.text_content() or "")
    body = clean_text(body_el.text_content() or "") if body_el is not None else full_text

    published_at = None
    m = re.search(r"(?:发布时间|发布日期|时间)[:：]\s*(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})", full_text)
    if m:
        published_at = _iso_from_match(m)
    else:
        m2 = DATE_RE.search(full_text[:800])
        if m2:
            published_at = _iso_from_match(m2)

    host = urlsplit(url).netloc
    ext: list[dict] = []
    attachments: list[dict] = []
    seen_ext: set[str] = set()
    for a in doc.xpath("//a[@href]"):
        raw = a.get("href") or ""
        href = urljoin(url, raw)
        if not href.startswith(("http://", "https://")):
            continue
        if any(k in raw.lower() for k in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", "download.jsp")):
            attachments.append({"name": clean_text(a.text_content() or "")[:60], "url": href})
        h = urlsplit(href).netloc
        if h == host or (own_hosts and h in own_hosts):
            continue
        if any(h == s or h.endswith("." + s) for s in own_suffixes):  # 页脚/校内导航
            continue
        if h in blacklist or any(h.endswith("." + b) for b in blacklist):
            continue
        if href in seen_ext:
            continue
        seen_ext.add(href)
        ext.append({"text": clean_text(a.text_content() or "")[:60], "url": href})

    return {
        "title": title,
        "body": body,
        "full_text_len": len(full_text),
        "published_at": published_at,
        "external_links": ext[:15],
        "attachments": attachments[:10],
    }
