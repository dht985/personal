"""学校认定目录中的计算机相关赛事覆盖审计。"""

from __future__ import annotations

from collections import Counter
from datetime import date

from .config import Config


def is_cs_entry(entry, cfg: Config) -> bool:
    if entry is None:
        return False
    if entry.dept in ("软件学院", "信息学院"):
        return True
    return any(word in entry.name for word in cfg.keywords["cs_signals"])


def build_coverage(catalog, records: list[dict], cfg: Config) -> dict:
    """按目录条目核验是否发现记录、当年通知和官方来源。"""
    current_year = str(date.today().year)
    by_no = {
        int(record["catalog_no"]): record
        for record in records
        if record.get("catalog_no") is not None
    }
    entries = [entry for entry in catalog.entries if is_cs_entry(entry, cfg)]
    rows = []
    for entry in entries:
        record = by_no.get(entry.no)
        notices = (record or {}).get("notices", [])
        current_notices = [
            notice for notice in notices
            if current_year in (notice.get("title") or "")
            or str(notice.get("published_at") or notice.get("list_date") or "").startswith(
                current_year
            )
        ]
        official_sources = [
            notice for notice in notices
            if notice.get("authority") in ("official", "org", "other-official")
        ]
        direct_links = (record or {}).get("official_links") or []
        if current_notices and official_sources:
            status = "current_official"
        elif current_notices:
            status = "current_public"
        elif record is not None:
            status = "historical_only"
        else:
            status = "missing"
        rows.append({
            "catalog_no": entry.no,
            "name": entry.name,
            "category": entry.category,
            "dept": entry.dept,
            "status": status,
            "record_found": record is not None,
            "has_current_notice": bool(current_notices),
            "has_official_source": bool(official_sources or direct_links),
            "notice_count": len(notices),
            "official_links": direct_links[:5],
            "sample_notice": (current_notices or notices or [{}])[0].get("url", ""),
        })
    counts = Counter(row["status"] for row in rows)
    return {
        "generated_at": date.today().isoformat(),
        "total_catalog": len(catalog.entries),
        "cs_catalog": len(entries),
        "recorded": sum(1 for row in rows if row["record_found"]),
        "current_notice": sum(1 for row in rows if row["has_current_notice"]),
        "official_source": sum(1 for row in rows if row["has_official_source"]),
        "status_counts": dict(counts),
        "gaps": [
            row for row in rows
            if row["status"] in ("missing", "historical_only")
        ],
        "entries": rows,
    }


def search_candidates(
    catalog, records: list[dict], cfg: Config, limit: int,
) -> list:
    """从缺少记录或当年官方通知的目录赛事中轮转选择待查目标。"""
    current_year = str(date.today().year)
    by_no = {
        int(record["catalog_no"]): record
        for record in records
        if record.get("catalog_no") is not None
    }
    candidates = []
    for entry in catalog.entries:
        if not is_cs_entry(entry, cfg):
            continue
        record = by_no.get(entry.no)
        notices = (record or {}).get("notices", [])
        has_current = any(
            current_year in (notice.get("title") or "")
            or str(notice.get("published_at") or notice.get("list_date") or "").startswith(
                current_year
            )
            for notice in notices
        )
        if not has_current:
            candidates.append(entry)
    category_order = {"一类": 0, "二类": 1, "三类": 2, "四类": 3}
    candidates.sort(key=lambda entry: (category_order.get(entry.category, 9), entry.no))
    if limit <= 0 or len(candidates) <= limit:
        return candidates
    start = (date.today().isocalendar().week * limit) % len(candidates)
    rotated = candidates[start:] + candidates[:start]
    return rotated[:limit]
