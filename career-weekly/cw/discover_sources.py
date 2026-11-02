"""持续发现：巡检官网导航，为缺少招聘、政策或新闻栏目补充公开信源。

不使用搜索引擎结果页做网页抓取。搜索页通常有 robots 限制；本项目只在官网
公开导航内发现栏目。以后如需接入搜索 API，可在发现层增加合规的 API 适配器。
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from lxml import html

from .config import Config, source_purpose
from .net import Fetcher
from .store import Store

PURPOSE_SPECS = {
    "recruit": {
        "label": "招聘",
        "link_terms": ("招聘", "人才招聘", "校园招聘", "人才发展", "加入我们"),
        "page_terms": ("招聘", "岗位", "应届", "校园", "人才"),
    },
    "policy": {
        "label": "政策",
        "link_terms": (
            "信息公开", "政策", "规划", "战略", "制度", "通知公告",
            "公示公告", "企业公告", "集团公告",
        ),
        "page_terms": (
            "政策", "规划", "办法", "通知", "公告", "公示", "制度",
            "信息公开", "战略",
        ),
    },
    "news": {
        "label": "新闻/项目",
        "link_terms": ("新闻", "要闻", "动态", "科技", "研发", "创新", "项目"),
        "page_terms": ("新闻", "要闻", "动态", "科技", "研发", "创新", "项目"),
    },
}


def root_domain(url: str) -> str:
    host = urlsplit(url).netloc.lower().split(":")[0]
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in {"com.cn", "edu.cn", "gov.cn", "org.cn"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _same_site(url: str, root: str) -> bool:
    host = urlsplit(url).netloc.lower().split(":")[0]
    return host == root or host.endswith("." + root)


def _content_links(
    raw: str, base_url: str, root: str, min_title: int = 8,
) -> list[dict]:
    doc = html.fromstring(raw)
    out: list[dict] = []
    seen: set[str] = set()
    for a in doc.xpath("//a[@href]"):
        title = " ".join((a.text_content() or "").split())
        href = (a.get("href") or "").strip()
        if (
            not (min_title <= len(title) <= 100)
            or not href
            or href.startswith(("#", "javascript:"))
        ):
            continue
        url = urljoin(base_url, href).split("#")[0]
        parts = urlsplit(url)
        if (
            url in seen
            or parts.scheme not in ("http", "https")
            or not _same_site(url, root)
            or parts.path in ("", "/")
        ):
            continue
        seen.add(url)
        out.append({"title": title, "url": url})
    return out


def candidate_links(
    raw: str, base_url: str, purpose: str, unit_home: str,
) -> list[dict]:
    """从官网首页导航中挑选对应用途的栏目，按标题匹配强度排序。"""
    spec = PURPOSE_SPECS[purpose]
    root = root_domain(unit_home)
    scored: list[tuple[int, dict]] = []
    for link in _content_links(raw, base_url, root, min_title=2):
        title = link["title"]
        text_score = sum(1 for term in spec["link_terms"] if term in title)
        if not text_score:
            continue
        score = text_score * 10
        if purpose == "policy" and any(k in title for k in ("信息公开", "政策", "规划")):
            score += 4
        if purpose == "recruit" and "招聘" in title:
            score += 4
        scored.append((score, link))
    scored.sort(key=lambda pair: (-pair[0], len(pair[1]["title"])))
    return [item for _, item in scored[:8]]


def _page_has_profile(raw: str, base_url: str, purpose: str, unit_home: str) -> tuple[bool, str]:
    root = root_domain(unit_home)
    links = _content_links(raw, base_url, root)
    terms = PURPOSE_SPECS[purpose]["page_terms"]
    hits = [link for link in links if any(term in link["title"] for term in terms)]
    if len(links) < 3:
        return False, f"内容链接不足（{len(links)}）"
    if len(hits) < 2:
        return False, f"目标词链接不足（{len(hits)}）"
    return True, f"内容链接 {len(links)}，目标词链接 {len(hits)}"


def _recently_checked(store: Store, unit_id: str, purpose: str, url: str, days: int) -> bool:
    checked = store.discovery_checked_at(unit_id, purpose, url)
    if not checked:
        return False
    try:
        when = datetime.fromisoformat(checked)
        cutoff = datetime.now().astimezone() - timedelta(days=days)
        return when >= cutoff
    except ValueError:
        return False


def _unit_last_checked(store: Store, unit_id: str) -> str:
    row = store.conn.execute(
        """SELECT MAX(checked_at) AS latest FROM discovery_attempts
           WHERE unit_id = ?""",
        (unit_id,),
    ).fetchone()
    return (row["latest"] if row else "") or ""


def _candidate_units(cfg: Config, store: Store) -> list[dict]:
    covered: set[tuple[str, str]] = {
        (src.get("unit", ""), source_purpose(src)) for src in cfg.sources
    }
    units = [
        unit for unit in cfg.units
        if unit["id"] in set(cfg.focus)
        and unit.get("home")
        and any((unit["id"], purpose) not in covered for purpose in PURPOSE_SPECS)
    ]
    tier_order = {"core": 0, "watch": 1, "reserve": 2}
    units.sort(
        key=lambda unit: (
            _unit_last_checked(store, unit["id"]) or "0000",
            tier_order.get(unit.get("tier"), 9),
            -int(unit.get("level", 0)),
            unit.get("short", unit["id"]),
        )
    )
    return units


def discover(
    cfg: Config, limit: int = 4, retry_days: int = 30, log=print,
) -> list[dict]:
    """巡检最多 ``limit`` 个重点单位，补齐其全部缺失的公开数据通道。"""
    store = Store(cfg.db_path)
    fetcher = Fetcher(cfg)
    covered: set[tuple[str, str]] = {
        (src.get("unit", ""), source_purpose(src)) for src in cfg.sources
    }
    existing_urls = {src.get("url") for src in cfg.sources if src.get("url")}
    added: list[dict] = []
    units = _candidate_units(cfg, store)
    log(f"官网巡检：{len(units)} 个单位仍有缺失通道，本轮检查最多 {limit} 个")
    for unit in units[:limit]:
        home_page = fetcher.get(unit["home"])
        base_url = home_page.final_url or unit["home"]
        short = unit.get("short", unit["id"])
        if not home_page.ok:
            detail = home_page.error or f"HTTP {home_page.status}"
            for purpose in PURPOSE_SPECS:
                if (unit["id"], purpose) not in covered:
                    store.record_discovery(
                        unit["id"], purpose, "官网首页", unit["home"],
                        "home_error", detail,
                    )
            log(f"  {short}：官网不可访问（{detail}）")
            continue
        for purpose, spec in PURPOSE_SPECS.items():
            if (unit["id"], purpose) in covered:
                continue
            links = candidate_links(home_page.text, base_url, purpose, unit["home"])
            accepted = False
            for link in links:
                url = link["url"]
                if url in existing_urls:
                    continue
                if _recently_checked(store, unit["id"], purpose, url, retry_days):
                    continue
                page = fetcher.get(url)
                if not page.ok:
                    ok, detail = False, page.error or f"HTTP {page.status}"
                else:
                    ok, detail = _page_has_profile(
                        page.text, page.final_url, purpose, unit["home"],
                    )
                store.record_discovery(
                    unit["id"], purpose, link["title"], url,
                    "accepted" if ok else "rejected", detail,
                )
                log(f"  {short} · {spec['label']}：{link['title'][:24]} -> {detail}")
                if not ok:
                    continue
                item = {
                    "id": "auto-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:8],
                    "unit": unit["id"],
                    "purpose": purpose,
                    "name": f"{short}·{spec['label']}（自动发现）",
                    "url": url,
                    "auto": True,
                    "discovered_at": date.today().isoformat(),
                }
                added.append(item)
                existing_urls.add(url)
                covered.add((unit["id"], purpose))
                accepted = True
                log(f"  + {short} 新增{spec['label']}源：{url}")
                break
            if not accepted:
                store.record_discovery(
                    unit["id"], purpose, "官网首页导航", unit["home"],
                    "no_candidate", f"从首页发现 {len(links)} 个候选",
                )
    store.conn.close()
    return added


def save(cfg: Config, items: list[dict]) -> Path:
    path = cfg.base / "config" / "sources_auto.toml"
    old: list[dict] = []
    if path.exists():
        import tomllib
        with path.open("rb") as fh:
            old = tomllib.load(fh).get("source", [])
    known_urls = {item.get("url") for item in old}
    merged = old + [item for item in items if item.get("url") not in known_urls]
    lines = ["# 由 discover-sources 自动维护；保留已有记录，不覆盖静态人工信源。", ""]
    for item in merged:
        lines += [
            "[[source]]",
            f"id = {json.dumps(item['id'], ensure_ascii=False)}",
            f"unit = {json.dumps(item['unit'], ensure_ascii=False)}",
            f"purpose = {json.dumps(source_purpose(item), ensure_ascii=False)}",
            f"name = {json.dumps(item['name'], ensure_ascii=False)}",
            f"url = {json.dumps(item['url'], ensure_ascii=False)}",
            "auto = true",
            f"discovered_at = {json.dumps(item['discovered_at'], ensure_ascii=False)}",
            "",
        ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path
