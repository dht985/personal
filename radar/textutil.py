"""文本归一化与日期解析工具。"""

from __future__ import annotations

import re
from datetime import date

_WS = re.compile(r"[\s\u3000\xa0]+")
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "《": "", "》": ""})

_FULL_TO_HALF = {ord(c): ord(c) - 0xFEE0 for c in map(chr, range(0xFF01, 0xFF5F))}


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    return text.strip()


def squeeze(text: str) -> str:
    """去掉全部空白，用于名称指纹比较。"""
    return _WS.sub("", text or "")


def normalize_name(name: str) -> str:
    """赛事名称归一化：去空白/引号/括号内容/年份/破折号，保留中英文与数字。"""
    s = squeeze(name).translate(_QUOTES)
    s = s.translate(_FULL_TO_HALF)
    s = re.sub(r"[（）()\[\]【】]", "", s)
    s = re.sub(r"\d{4}\s*年?", "", s)
    s = re.sub(r"[·•・\-—_—~～,，.。:：;；/\\|]+", "", s)
    s = s.lower()
    s = s.replace("全国大学生", "").replace("中国大学生", "").replace("全国高校", "")
    return s


def full_width_to_half(text: str) -> str:
    return (text or "").translate(_FULL_TO_HALF)


DATE_FULL = re.compile(
    r"(?P<y>20\d{2})\s*[年./\-]\s*(?P<m>\d{1,2})\s*[月./\-]\s*(?P<d>\d{1,2})\s*日?"
)
DATE_SHORT = re.compile(r"(?<!\d)(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日?")


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def find_dates(text: str, base_year: int | None = None) -> list[dict]:
    """返回文本中所有日期，附带原文片段与字符位置。"""
    out: list[dict] = []
    seen_spans: list[tuple[int, int]] = []
    for m in DATE_FULL.finditer(text):
        iso = _iso(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        if iso:
            out.append({"value": iso, "raw": m.group(0), "start": m.start(), "end": m.end()})
            seen_spans.append((m.start(), m.end()))
    if base_year:
        for m in DATE_SHORT.finditer(text):
            if any(s <= m.start() < e for s, e in seen_spans):
                continue
            iso = _iso(base_year, int(m.group("m")), int(m.group("d")))
            if iso:
                out.append(
                    {"value": iso, "raw": m.group(0), "start": m.start(), "end": m.end()}
                )
    out.sort(key=lambda x: x["start"])
    return out


def snippet_around(text: str, start: int, end: int, pad: int = 45) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    return text[lo:hi].strip()


def guess_publish_year(text: str) -> int | None:
    m = re.search(r"(20\d{2})\s*[年./\-]", text or "")
    return int(m.group(1)) if m else None


def canonical_url(url: str) -> str:
    """同一页面的 http/https、带不带 www、结尾斜杠都算同一个地址。"""
    if not url:
        return ""
    u = url.strip().split("#")[0]
    m = re.match(r"^(https?)://([^/]+)(/.*)?$", u, re.IGNORECASE)
    if not m:
        return u
    host = m.group(2).lower()
    if host.startswith("www."):
        host = host[4:]
    path = (m.group(3) or "/").rstrip("/") or "/"
    return f"{host}{path}".lower()
