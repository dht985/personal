from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urljoin, urlsplit

from lxml import html as lxml_html

DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
NAV_WORDS = {
    "首页", "更多", "更多>>", "下一页", "上一页", "尾页", "English", "登录",
    "注册", "联系我们", "网站地图", "返回", "关闭",
}
NAV_TITLE_RE = re.compile(r"^(员工发展|人才理念|招聘信息|人才招聘|加入我们|校园招聘首页)")


def _iso(m) -> str | None:
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except (ValueError, TypeError):
        return None


def parse_list(raw: str, base_url: str, limit: int = 40, lookback_days: int = 90) -> list[dict]:
    doc = lxml_html.fromstring(raw)
    for bad in doc.xpath("//script|//style|//noscript"):
        bad.getparent().remove(bad)

    items: list[dict] = []
    seen: set[str] = set()
    today = dt.date.today()
    for a in doc.xpath("//a[@href]"):
        href = a.get("href") or ""
        if not href or href.startswith(("#", "javascript:")):
            continue
        title = " ".join((a.text_content() or "").split())
        if not (8 <= len(title) <= 90) or title in NAV_WORDS:
            continue
        if NAV_TITLE_RE.search(title):
            continue
        # 成员企业名称不是新闻
        if re.search(r"(有限公司|股份有限公司|集团)$", title):
            continue
        full = urljoin(base_url, href).split("#")[0]
        parts = urlsplit(full)
        if full in seen or parts.scheme not in ("http", "https"):
            continue
        # 成员企业/友情链接通常指向首页，不是新闻
        if parts.path in ("", "/"):
            continue
        seen.add(full)

        parent = a.getparent()
        context = ""
        for _ in range(3):
            if parent is None:
                break
            context = " ".join((parent.text_content() or "").split())
            if DATE_RE.search(context):
                break
            parent = parent.getparent()
        m = DATE_RE.search(context or "")
        published = _iso(m) if m else None
        if published:
            try:
                if (today - dt.date.fromisoformat(published)).days > lookback_days:
                    continue
            except ValueError:
                pass
        items.append(
            {
                "title": title,
                "url": full,
                "published_at": published,
            }
        )
        if len(items) >= limit:
            break
    return items
