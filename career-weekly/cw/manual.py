"""人工维护源：按固定格式的 Markdown 列表读入条目。"""

from __future__ import annotations

import re
from pathlib import Path

LINE_RE = re.compile(r"^\s*[-*]\s*\[(?P<title>[^\]]+)\]\((?P<url>[^)]+)\)\s*(?:\|\s*(?P<date>\d{4}-\d{2}-\d{2}))?")


def parse(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        out.append(
            {
                "title": m.group("title").strip(),
                "url": m.group("url").strip(),
                "published_at": m.group("date"),
            }
        )
    return out
