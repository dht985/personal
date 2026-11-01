"""L3 候选发现：从单位首页找部门/实验室/研究所链接，只给建议，不自动建单位。"""

from __future__ import annotations

import re
import hashlib
from urllib.parse import urljoin

from lxml import html as lxml_html

from .config import Config
from .net import Fetcher

DEPT_RE = re.compile(r"(事业部|实验室|研究所|研究院|研发中心|技术中心|创新中心|部门|中心)$")


def candidates(cfg: Config, fetcher: Fetcher, log=print) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for unit in cfg.units:
        if int(unit.get("level", 0)) != 2 or not unit.get("home"):
            continue
        page = fetcher.get(unit["home"])
        if not page.ok:
            log(f"  {unit['short']}: 首页抓取失败（{page.error or page.status}）")
            continue
        doc = lxml_html.fromstring(page.text)
        for a in doc.xpath("//a[@href]"):
            text = " ".join((a.text_content() or "").split())
            if not (4 <= len(text) <= 40) or not DEPT_RE.search(text):
                continue
            url = urljoin(page.final_url, a.get("href") or "")
            key = f"{unit['id']}|{text}"
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "parent": unit["id"],
                    "parent_short": unit.get("short", unit["name"]),
                    "name": text,
                    "url": url,
                }
            )
    return out


def render_toml(items: list[dict]) -> str:
    lines = ["# 自动发现的 L3 候选，请人工确认后再挪到 units.toml"]
    for it in items:
        lines += [
            "",
            "[[unit]]",
            f'id = "{it["parent"]}-l3-{hashlib.sha1(it["name"].encode("utf-8")).hexdigest()[:6]}"',
            f'name = "{it["name"]}"',
            f'level = 3',
            f'parent = "{it["parent"]}"',
            'category = "待确认"',
            'region = "待确认"',
            'tier = "reserve"',
            f'home = "{it["url"]}"',
            'note = "自动发现，待人工确认"',
        ]
    return "\n".join(lines) + "\n"
