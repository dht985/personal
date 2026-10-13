"""网页仪表盘：把结构化结果渲染成一个自包含的 HTML 文件。

刻意不引入任何前端依赖和 CDN：CSS/JS 内联，数据以 JSON 内嵌，
生成后双击就能看，断网也能看，也方便直接发给别人。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import Config
from .report import TIER_ORDER, best_notice

TEMPLATE_PATH = Path(__file__).with_name("dashboard_template.html")
DATA_PLACEHOLDER = "/*__DATA__*/"


def _search_text(record: dict) -> str:
    parts = [record.get("name", "")]
    parts += [n.get("title", "") or "" for n in record.get("notices", [])]
    parts += [n.get("body_excerpt", "") or "" for n in record.get("notices", [])]
    for key in ("organizer_text", "fee_text", "team_text", "eligibility_text"):
        parts.append(record.get(key) or "")
    return " ".join(parts)[:2000]


def build_payload(
    records: list[dict],
    discovery: list[dict],
    stats: dict,
    catalog_meta: dict,
    changes: list[dict],
    pushes: list[dict],
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    tier_counts = {t: 0 for t in TIER_ORDER}
    for r in records:
        tier_counts[r["tier"]] = tier_counts.get(r["tier"], 0) + 1

    out_records = []
    for r in records:
        primary = best_notice(r) or {}
        out_records.append(
            {
                "key": r["key"],
                "name": r["name"],
                "tier": r["tier"],
                "score_total": r.get("score_total"),
                "catalog_category": r.get("catalog_category"),
                "catalog_no": r.get("catalog_no"),
                "catalog_dept": r.get("catalog_dept"),
                "cs_fit": r.get("cs_fit"),
                "deadline_status": r.get("deadline_status"),
                "deadline_detail": r.get("deadline_detail"),
                "registration_first": r.get("registration_first"),
                "registration_last": r.get("registration_last"),
                "tier_reason": r.get("tier_reason", ""),
                "szcp_estimate": r.get("szcp_estimate"),
                "risks": r.get("risks", []),
                "next_actions": r.get("next_actions", []),
                "dimensions": r.get("dimensions", []),
                "notices": [
                    {
                        "title": n.get("title"),
                        "url": n.get("url"),
                        "source_name": n.get("source_name"),
                        "published_at": n.get("published_at") or n.get("list_date"),
                    }
                    for n in r.get("notices", [])
                ],
                "registration_evidence": r.get("registration_evidence", [])[:3],
                "achievements": r.get("achievements", []),
                "official_links": r.get("official_links", [])[:5],
                "first_seen": (r.get("first_seen") or "")[:19],
                "last_verified": (r.get("last_verified") or "")[:19],
                "authority": r.get("authority"),
                "history_years": r.get("history_years", []),
                "primary_url": primary.get("url", ""),
                "primary_source": primary.get("source_name") or primary.get("title") or "",
                "search_text": _search_text(r),
            }
        )

    kept = [d for d in discovery if d.get("kept")]
    return {
        "generated_at": generated_at,
        "catalog": {
            "title": catalog_meta.get("title", "未加载"),
            "count": catalog_meta.get("count", 0),
            "version": catalog_meta.get("version", ""),
            "source_url": catalog_meta.get("source_url", ""),
        },
        "stats": stats,
        "tier_counts": tier_counts,
        "chips": [
            ("赛事实体", stats.get("records", len(out_records))),
            ("重点关注", tier_counts.get("重点关注", 0)),
            ("潜在机会", tier_counts.get("潜在机会", 0)),
            ("低优先级/证据不足", tier_counts.get("低优先级/证据不足", 0)),
            ("官方通知", stats.get("official_notices", 0)),
            ("发现通道命中", stats.get("discovery_kept", 0)),
            ("本轮变化", len(changes)),
            ("本轮提醒", stats.get("notifications", 0)),
        ],
        "records": out_records,
        "changes": [
            {"time": generated_at[11:19], "type": c.get("type", ""),
             "name": c.get("name", ""), "detail": c.get("detail", "")}
            for c in changes
        ],
        "pushes": pushes,
        "discovery": [
            {"title": d.get("title", ""), "real_url": d.get("real_url", ""),
             "catalog_category": d.get("catalog_category")}
            for d in kept[:40]  # 页面只展示前 40 条，完整清单看 data/candidates.json
        ],
        "discovery_total": len(kept),
        "notes": [
            "目录认定、综合测评赋分、保研价值是三个不同概念，本页分维度呈现，不互相替代。",
            "综合测评赋分已按《2023级计科综合评测细则》算出：加分 = 基础分 × 分类权重 × 获奖权重 × 排名权重，"
            "本项上限 5 分；卡片上的数值是「国家级一等奖 + 团队排名第一」的上限情形。",
            "认定目录已更新为《学校认定本科生学科竞赛目录（2026版）》；"
            "列入 2025 版但未列入 2026 版的竞赛按细则降一级计算。",
            "所有日期均来自通知原文抽取并附原文片段；抽不到时明确标注，未做推测。",
            "学生评价维度只在有可靠公开来源时才呈现，否则写「未找到足够可靠的公开评价」。",
        ],
    }


def render_dashboard(payload: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, default=str)
    # 防止正文里出现 </script> 把脚本块提前截断
    data = data.replace("</", "<\\/")
    return template.replace(DATA_PLACEHOLDER, data)


def write_dashboard(cfg: Config, payload: dict) -> Path:
    html = render_dashboard(payload)
    path = cfg.outbox_dir / "dashboard.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
