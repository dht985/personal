from __future__ import annotations

from datetime import date
from pathlib import Path
import re

from .classify import is_relevant, match_tags, match_tracks, signal_type
from .browser import render_many
from .config import Config
from .llm import triage_batch
from .manual import parse as parse_manual
from .net import Fetcher
from .parse import parse_list
from .report import render
from .store import Store
from .toast import send as send_toast


def _event_key(title: str) -> str:
    """同一事件在不同来源的标题可能带日期前缀或标点差异。"""
    t = re.sub(r"^20\d{2}[.\-/年]\d{1,2}[.\-/月]\d{1,2}日?\s*", "", title or "")
    return re.sub(r"[\s\W_]+", "", t)[:60]


def run(
    cfg: Config, limit: int | None = None, use_llm: bool = True,
    use_detail: bool = True, log=print,
) -> dict:
    cfg.ensure_dirs()
    store = Store(cfg.db_path)
    store.start_run()
    fetcher = Fetcher(cfg)
    units = cfg.unit_map()
    max_items = limit or int(cfg.settings["report"]["max_items"])

    raw_items: list[dict] = []
    seen_urls: set[str] = set()
    failed: list[str] = []
    active = set(cfg.focus)
    active_sources = [s for s in cfg.sources if s.get("unit") in active]
    render_urls = [s["url"] for s in active_sources if s.get("render")]
    rendered = render_many(render_urls, cfg.raw_dir) if render_urls else {}
    for src in active_sources:
        if src.get("kind") == "manual":
            unit = units.get(src["unit"], {})
            for it in parse_manual(cfg.base / src["path"]):
                sig = signal_type(it["title"]) or "技术"
                item = {
                    **it,
                    "source_id": src["id"],
                    "source_name": src["name"],
                    "unit_id": src["unit"],
                    "unit_path": cfg.path_of(src["unit"]),
                    "level": int(unit.get("level", 0)),
                    "signal_type": sig,
                    "tracks": match_tracks(it["title"], cfg.tracks),
                    "tags": match_tags(it["title"], cfg.tags),
                }
                item["is_new"] = store.upsert(item)
                raw_items.append(item)
            continue
        if src.get("render"):
            html = rendered.get(src["url"], "")
            if not html:
                failed.append(f"{src['name']}（浏览器渲染失败）")
                continue
            page = type("P", (), {"ok": True, "text": html, "final_url": src["url"], "status": 200})()
        else:
            page = fetcher.get(src["url"])
            if not page.ok:
                failed.append(f"{src['name']}（{page.error or page.status}）")
                continue
        unit = units.get(src["unit"], {})
        lookback = int(cfg.settings.get("run", {}).get("lookback_days", 180))
        for it in parse_list(page.text, page.final_url, lookback_days=lookback):
            sig = signal_type(it["title"])
            if sig is None:
                continue
            if not is_relevant(it["title"]):
                continue
            item = {
                **it,
                "source_id": src["id"],
                "source_name": src["name"],
                "unit_id": src["unit"],
                "unit_path": cfg.path_of(src["unit"]),
                "level": int(unit.get("level", 0)),
                "signal_type": sig,
                "tracks": match_tracks(it["title"], cfg.tracks),
                "tags": match_tags(it["title"], cfg.tags),
            }
            # 校招汇总源：标题里出现哪家单位，就归到哪家
            if item["unit_id"] == "ynu-career":
                for uid, unit in units.items():
                    if uid == "ynu-career":
                        continue
                    names = [unit.get("short", ""), unit.get("name", "")]
                    if any(n and n in item["title"] for n in names):
                        item["unit_id"] = uid
                        item["level"] = int(unit.get("level", 0))
                        item["unit_path"] = cfg.path_of(uid)
                        break
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            item["is_new"] = store.upsert(item)
            raw_items.append(item)
        log(f"  {src['name']}: {len(raw_items)} 条累计")

    # 跨源去重：同一事件在集团/子公司都发时，按"标题+日期"归并，保留更具体的层级
    by_event: dict[tuple[str, str], dict] = {}
    duplicates = 0
    for item in raw_items:
        key = (_event_key(item["title"]), item.get("published_at") or "")
        prev = by_event.get(key)
        if prev is None:
            by_event[key] = item
        elif item["level"] > prev["level"]:
            by_event[key] = item
            duplicates += 1
        else:
            duplicates += 1
    raw_items = list(by_event.values())

    # 先按规则排序，再交给 AI 做批量收录判断（不做解读）
    raw_items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
    raw_items.sort(
        key=lambda x: (
            {"招聘": 0, "采购": 1, "项目": 2, "投资": 3, "战略": 4, "技术": 5}[x["signal_type"]],
            not x["is_new"],
        )
    )

    pool = raw_items[:60]
    triaged: list[dict] = []
    fallback_batches = 0
    for start in range(0, len(pool), 8):
        chunk = pool[start:start + 8]
        decisions = triage_batch(chunk, cfg.settings) if use_llm else {}
        if use_llm and not decisions:
            fallback_batches += 1
        for i, item in enumerate(chunk):
            d = decisions.get(i)
            if d is None:
                item["triage"] = {"include": True, "reason": "规则命中"}
            else:
                item["triage"] = d
            triaged.append(item)

    included = [i for i in triaged if i["triage"]["include"]]

    # 层级配额 + 单单位上限，避免某一家刷屏
    per_unit = int(cfg.settings["report"].get("max_items_per_unit", 3))
    quotas = {1: 8, 2: 3, 3: 1}
    signal_quota = {"招聘": 6, "采购": 2, "项目": 4, "投资": 2, "战略": 2, "技术": 4}
    selected: list[dict] = []
    used: dict[str, int] = {}
    sig_used: dict[str, int] = {}
    level_used: dict[int, int] = {1: 0, 2: 0, 3: 0}
    # 先取更具体的 L2/L3，再补集团层，避免 L1 把配额吃光
    for level in (2, 3, 1):
        taken = 0
        for item in included:
            if item["level"] != level or taken >= quotas[level]:
                continue
            if used.get(item["unit_id"], 0) >= per_unit:
                continue
            if sig_used.get(item["signal_type"], 0) >= signal_quota[item["signal_type"]]:
                continue
            selected.append(item)
            used[item["unit_id"]] = used.get(item["unit_id"], 0) + 1
            sig_used[item["signal_type"]] = sig_used.get(item["signal_type"], 0) + 1
            level_used[level] = level_used.get(level, 0) + 1
            taken += 1
    for item in included:
        if len(selected) >= max_items:
            break
        if item in selected or used.get(item["unit_id"], 0) >= per_unit:
            continue
        if sig_used.get(item["signal_type"], 0) >= signal_quota[item["signal_type"]]:
            continue
        selected.append(item)
        used[item["unit_id"]] = used.get(item["unit_id"], 0) + 1
        sig_used[item["signal_type"]] = sig_used.get(item["signal_type"], 0) + 1
    selected = selected[:max_items]

    stats = {
        "sources_total": len(active_sources),
        "sources_ok": len(active_sources) - len(failed),
        "failed_sources": len(failed),
        "failed_sources_list": failed,
        "raw_items": len(raw_items),
        "new_items": sum(1 for i in raw_items if i["is_new"]),
        "duplicates": duplicates,
        "triaged": len(triaged),
        "ai_included": len(included),
        "ai_excluded": len(triaged) - len(included),
        "triage_fallback_batches": fallback_batches,
        "llm_fallbacks": fallback_batches,
        "detail_fetched": 0,
    }
    text = render(selected, cfg, stats)
    out = cfg.outbox_dir / f"weekly-{date.today().isoformat()}.md"
    out.write_text(text, encoding="utf-8")
    (cfg.outbox_dir / "weekly-latest.md").write_text(text, encoding="utf-8")
    stats["report"] = str(out)
    stats["chars"] = len(text)

    notify = cfg.settings.get("notify", {})
    if notify.get("enabled", True):
        ok, detail = send_toast(
            f"职业情报周报：{stats['new_items']} 条新增",
            f"覆盖 {stats['sources_ok']}/{stats['sources_total']} 个信源",
            str(out),
        )
        stats["toast"] = {"ok": ok, "detail": detail}
    if notify.get("open_report", False):
        import os
        try:
            os.startfile(str(out))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    store.finish_run(stats)
    store.conn.close()
    return stats
