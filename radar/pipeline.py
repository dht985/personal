"""流水线编排：采集 -> 解析 -> 抽取 -> 归并 -> 评估 -> 输出。"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import Config
from .catalog import Catalog
from .dashboard import build_payload, write_dashboard
from .evaluate import cs_fit, evaluate, explain_tier
from .extract import extract_fields, guess_competition_name, summarize_dates
from .net import Fetcher
from .notify import dispatch
from .report import best_notice, render_card, render_digest, render_notifications
from .requirement import assess_requirement
from .sources import Notice, collect_discovery, collect_official, enrich_details
from .store import Change, Store, TRACKED_FIELDS
from .szcp import SzcpRules
from .textutil import canonical_url, normalize_name, squeeze
from .ynu_profile import assess as assess_ynu
from .ynu_profile import build_corpus
from .ynu_profile import engine_alive
from .ynu_profile import PROFILE_VERSION


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _is_cs_related(title: str, cfg: Config) -> bool:
    if any(w in title for w in cfg.keywords["cs_signals"]):
        return True
    return any(w in title for w in cfg.keywords.get("always_track", []))


def _entry_is_cs(entry, cfg: Config) -> bool:
    """目录条目是否属于计算机及相关方向：由承办学院或赛事名判断。"""
    if entry is None:
        return False
    if entry.dept in ("软件学院", "信息学院"):
        return True
    return any(w in entry.name for w in cfg.keywords["cs_signals"])


COMPETITION_NOTICE_RE = re.compile(
    r"竞赛|大赛|比赛|挑战赛|选拔赛|赛道|报名|征集|作品|程序设计|锦标赛|赛事"
)
ACHIEVEMENT_RE = re.compile(r"获奖|斩获|荣获|佳绩|喜报|夺魁|一等奖|二等奖|三等奖|奖项|夺奖")
NOTICE_WORD_RE = re.compile(r"通知|报名|征集|选拔|开始|启动|关于")


def classify_notice(title: str) -> str:
    """官方栏目里有三类内容：赛事通知、获奖新闻、与赛事无关的学院动态。"""
    if ACHIEVEMENT_RE.search(title) and not NOTICE_WORD_RE.search(title):
        return "achievement"
    if COMPETITION_NOTICE_RE.search(title):
        return "notice"
    return "other"


def _keep_discovery(item: dict, cfg: Config) -> bool:
    """过滤搜索结果里的导航页/无关页，只留下像赛事通知的条目。"""
    title = item.get("title", "")
    if len(title) < 8:
        return False
    if not re.search(r"竞赛|大赛|比赛|赛道|赛事|挑战赛|通知|报名|选拔", title):
        return False
    if re.search(r"首页|导航|平台|排名|攻略|经验分享|题库", title):
        return False
    url = item.get("real_url") or ""
    if not url.startswith("http"):
        return False
    cs_like = any(w in title for w in cfg.keywords["cs_signals"])
    edu_like = ".edu.cn" in url or ".gov.cn" in url or "cahe.edu.cn" in url
    return bool(cs_like or edu_like)


OTHER_SCHOOL_INTERNAL_RE = re.compile(r"校级|校赛|校内赛")
EXAM_NOISE_RE = re.compile(r"等级考试|考点|考试报名|四六级|普通话")
AWARD_NEWS_RE = re.compile(r"斩获|荣获|夺冠|获佳绩|冠军|获奖")
PORTAL_RE = re.compile(r"官网$|报名入口|本地宝|赛氪|竞赛网|题库|攻略|专题|门户")
NOTICE_HINT_RE = re.compile(r"通知|报名|启动|开赛|征集|选拔|赛道|赛项")


def _is_discoverable_competition(title: str, url: str) -> bool:
    """发现通道里只保留"赛事"，并剔除外校校赛、等级考试这类噪声。"""
    if EXAM_NOISE_RE.search(title or ""):
        return False
    if OTHER_SCHOOL_INTERNAL_RE.search(title or "") and not re.search(r"云南大学|云大", title or ""):
        return False
    # 外校的获奖新闻不是"发现新赛事"，只是别人拿了奖
    if AWARD_NEWS_RE.search(title or "") and not re.search(r"通知|报名|启动|开赛", title or ""):
        return False
    # 竞赛导航站/官网首页没有可行动的信息
    if PORTAL_RE.search(title or ""):
        return False
    # 栏目名本身不是赛事（如"竞赛通知-云南大学信息学院"）
    head = (title or "").split("-")[0].strip()
    if head in {"竞赛通知", "竞赛动态", "新闻动态", "通知公告", "学院新闻", "学科竞赛", "竞赛概况"}:
        return False
    # 搜索引擎自己的结果页不能当赛事页
    if re.search(r"(^|\.)(so\.com|sogou\.com)", url or ""):
        return False
    # 既不像通知、又不在教育/政府域名上的，多半是平台首页或第三方文章
    if not NOTICE_HINT_RE.search(title or "") and not re.search(r"\.(edu|gov)\.cn", url or ""):
        return False
    return True


def _first_nonempty(values: list[str]) -> str | None:
    for v in values:
        if v:
            return v
    return None


def _entry_key(entry) -> str:
    """赛事实体的稳定标识。

    刻意不用目录序号：2026 版目录从 126 项变成 111 项，序号会整体位移，
    用序号当主键会让同一场比赛在新版目录里"重新投胎"。
    """
    return "catalog:" + squeeze(entry.name)


def _append_notice(rec: dict, notice: dict) -> None:
    """同一页面可能以 http/https、带不带 www 的形态重复出现，按规范化地址去重。"""
    key = canonical_url(notice["url"])
    for existing in rec["notices"]:
        if canonical_url(existing["url"]) == key:
            return
    rec["notices"].append(notice)


def _append_evidence(rec: dict, items: list[dict], limit: int = 6) -> None:
    seen = {e.get("evidence") for e in rec["registration_evidence"]}
    for item in items:
        if not item.get("evidence") or item["evidence"] in seen:
            continue
        seen.add(item["evidence"])
        rec["registration_evidence"].append(item)
        if len(rec["registration_evidence"]) >= limit:
            return


FIELD_CHANGE_TYPES = {
    "registration_first": "日期变化",
    "registration_last": "日期变化",
    "tier": "等级变化",
    "catalog_category": "目录类别变化",
    "fee_text": "费用变化",
    "team_text": "组队规则变化",
    "eligibility_text": "参赛资格变化",
    "contest_time_text": "赛程变化",
    "organizer_text": "主办方变化",
    "name": "名称变化",
}
FIELD_LABELS = {
    "registration_first": "报名开始",
    "registration_last": "报名截止",
    "tier": "关注等级",
    "catalog_category": "认定目录类别",
    "fee_text": "费用",
    "team_text": "组队要求",
    "eligibility_text": "参赛对象",
    "contest_time_text": "赛程时间",
    "organizer_text": "主办方",
    "name": "赛事名称",
}


def _load_szcp(cfg: Config) -> dict | None:
    if cfg.szcp_path.exists():
        try:
            return json.loads(cfg.szcp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def _detect_changes(prev, rec: dict) -> list[Change]:
    """把本次结果和数据库里上一次的结果逐字段比对。"""
    if prev is None:
        return []
    out: list[Change] = []
    for field in TRACKED_FIELDS:
        old = prev[field] if field in prev.keys() else None
        new = rec.get(field)
        if (old or "") == (new or ""):
            continue
        out.append(
            Change(
                competition=rec["name"],
                change_type=FIELD_CHANGE_TYPES.get(field, "字段变化"),
                field=field,
                old_value=old,
                new_value=new,
                detail=f"{FIELD_LABELS.get(field, field)}：{old or '空'} → {new or '空'}",
            )
        )
    return out


def _push_body(rec: dict) -> str:
    cat = rec.get("catalog_category") or "未收录认定目录"
    lines = [
        f"赛事等级：{rec['tier']}（总分 {rec.get('score_total')}）",
        f"云南大学认定目录：{cat}",
        f"报名截止：{rec.get('registration_last') or '通知中未写明'}（{rec.get('deadline_status')}）",
        f"适配度：{rec.get('cs_fit')}",
    ]
    if rec.get("registration_evidence"):
        lines.append(f"原文依据：{rec['registration_evidence'][0].get('evidence', '')[:120]}")
    best = best_notice(rec)
    if best:
        lines.append(f"通知来源：{best['url']}")
        if best.get("authority") != "official" or "ynu.edu.cn" not in (best.get("url") or ""):
            lines.append("注意：该来源不是云南大学官方通知，校内是否组织需要进一步确认")
    return "\n".join(lines)


def _queue_pushes(
    store: Store, comp_id: int, rec: dict, prev, rec_changes: list[Change],
    prev_notice_keys: set[str], catalog_title: str = "学校认定本科生学科竞赛目录",
) -> int:
    """只对"新赛事 / 需要行动 / 重要变化"排队推送，同一件事只推一次。"""
    created = 0

    def queue(kind: str, discriminator: str, title: str, body: str) -> None:
        nonlocal created
        key = f"{rec['key']}|{kind}|{discriminator}"
        if store.queue_push(key, comp_id, rec["name"], kind, title, body):
            created += 1

    if prev is None and rec["tier"] in ("重点关注", "潜在机会"):
        queue("首次发现", rec["first_seen"][:10],
              f"新赛事：{rec['name']}", _push_body(rec))

    # 校内确实发了通知、但不在认定目录里的计算机类赛事：值得单独提醒一次
    if (
        prev is None
        and rec.get("cs_fit") == "核心"
        and not rec.get("catalog_category")
        and rec.get("notices")
    ):
        queue(
            "新赛事待确认",
            rec["first_seen"][:10],
            f"新赛事待确认：{rec['name']}",
            _push_body(rec)
            + f"\n该赛事不在《{catalog_title}》中，"
              "建议向学院或本科生院确认是否纳入认定范围。",
        )

    if rec.get("deadline_status") == "30天内截止":
        queue("临近截止", rec.get("registration_last") or "unknown",
              f"临近截止：{rec['name']}", _push_body(rec))

    for ch in rec_changes:
        if ch.field == "registration_last":
            queue("日期变更", f"{ch.old_value}->{ch.new_value}",
                  f"报名截止日期变化：{rec['name']}", _push_body(rec))

    if prev is not None and prev["tier"] != "重点关注" and rec["tier"] == "重点关注":
        # 带上日期，避免同一赛事一生只能推一次"升级"（降级后再升级也应提醒）
        queue(
            "等级提升",
            f"{prev['tier']}->{rec['tier']}@{date.today().isoformat()}",
            f"升级为重点关注：{rec['name']}",
            _push_body(rec),
        )

    new_keys = {canonical_url(n["url"]) for n in rec["notices"]} - prev_notice_keys
    if prev is not None and new_keys and rec["tier"] == "重点关注":
        queue("新增通知", sorted(new_keys)[0],
              f"重点关注赛事有新通知：{rec['name']}", _push_body(rec))
    return created


def run_pipeline(
    cfg: Config,
    *,
    offline: bool = False,
    use_search: bool = True,
    force: bool = False,
    detail_limit: int | None = None,
    log=print,
) -> dict:
    cfg.ensure_dirs()
    fetcher = Fetcher(cfg, offline=offline, force=force)
    catalog = Catalog.load(cfg.catalog_path)
    catalog_prev = Catalog.load(cfg.catalog_prev_path)
    catalog_meta = catalog.meta
    lookback = cfg.settings["run"]["lookback_days"]
    cutoff = date.today() - timedelta(days=lookback)
    stats: dict = {"catalog_entries": len(catalog.entries)}

    log(f"[1/6] 采集官方栏目（目录已加载 {len(catalog.entries)} 项）")
    notices, log_rows = collect_official(cfg, fetcher)
    stats["official_notices"] = len(notices)

    # 只看最近一段时间发布的通知
    recent: list[Notice] = []
    for n in notices:
        d = n.list_date
        if d:
            try:
                if datetime.fromisoformat(d).date() < cutoff:
                    continue
            except ValueError:
                pass
        recent.append(n)
    stats["official_notices_recent"] = len(recent)

    cs_notices: list[Notice] = []
    achievements: list[tuple[Notice, object]] = []
    dropped = 0
    for n in recent:
        kind = classify_notice(n.title)
        entry, score, _ = catalog.match(guess_competition_name(n.title))
        catalog_like = bool(entry) and score >= 0.9 and _entry_is_cs(entry, cfg)
        if kind == "notice":
            if _is_cs_related(n.title, cfg) or catalog_like:
                cs_notices.append(n)
            else:
                dropped += 1
        elif kind == "achievement":
            if entry:
                achievements.append((n, entry))
            else:
                dropped += 1
        else:
            dropped += 1
    stats["cs_notices"] = len(cs_notices)
    stats["dropped_notices"] = dropped
    stats["achievement_news"] = len(achievements)
    log(
        f"      窗口内通知 {len(recent)} 条 -> 赛事通知 {len(cs_notices)} 条、"
        f"获奖新闻 {len(achievements)} 条、过滤 {dropped} 条"
    )

    log("[2/6] 抓取通知详情页")
    enrich_details(cfg, fetcher, cs_notices, limit=detail_limit)
    stats["detail_fetched"] = sum(1 for n in cs_notices if n.body)

    log("[3/6] 字段抽取与目录匹配")
    records: dict[str, dict] = {}
    for n in cs_notices:
        guessed = guess_competition_name(n.title)
        entry, score, method = catalog.match(guessed)
        prev_entry = None
        if entry is None:
            # 2026 目录里没有，看看 2025 目录里有没有：细则对这类竞赛按降一级处理，
            # 所以它仍然值得跟踪，只是类别要降档。
            prev_entry, prev_score, prev_method = catalog_prev.match(guessed)
            if prev_entry is not None:
                score, method = prev_score, f"{prev_method}(2025目录)"
        if entry:
            key = _entry_key(entry)
            name = entry.name
            cat_no, cat_cat, cat_dept = entry.no, entry.category, entry.dept
        elif prev_entry is not None:
            key = _entry_key(prev_entry)
            name = prev_entry.name
            cat_no, cat_cat, cat_dept = prev_entry.no, None, prev_entry.dept
        else:
            key = "name:" + (normalize_name(guessed) or normalize_name(n.title))
            name = guessed or n.title
            cat_no, cat_cat, cat_dept = None, None, None

        prev_cat = prev_entry.category if prev_entry is not None else None

        extracted = extract_fields(
            n.title,
            n.body,
            n.url,
            external_links=n.external_links,
            published_at=n.published_at,
        )
        summary = summarize_dates(extracted)

        rec = records.get(key)
        if rec is None:
            rec = {
                "key": key,
                "name": name,
                "catalog_no": cat_no,
                "catalog_category": cat_cat,
                "catalog_dept": cat_dept,
                "catalog_category_prev": prev_cat,
                "catalog_match_method": method,
                "catalog_match_score": score,
                "notices": [],
                "sources": [],
                "official_links": [],
                "student_reviews": [],
                "registration_evidence": [],
            }
            records[key] = rec

        _append_notice(
            rec,
            {
                "title": n.title,
                "url": n.url,
                "source_id": n.source_id,
                "source_name": n.source_name,
                "authority": n.authority,
                "published_at": n.published_at,
                "list_date": n.list_date,
                "fetched_at": n.fetched_at,
                "body_excerpt": (n.body or "")[:800],
            }
        )
        rec["sources"].append(n.source_name)
        for link in (n.external_links or []):
            url = link.get("url")
            if url and url not in rec["official_links"]:
                rec["official_links"].append(url)
        if not rec.get("registration_last"):
            rec["registration_first"] = summary["registration_first"]
            rec["registration_last"] = summary["registration_last"]
        _append_evidence(rec, extracted["registration"])
        for field, out_field in (
            ("fee", "fee_text"),
            ("team", "team_text"),
            ("eligibility", "eligibility_text"),
            ("organizer", "organizer_text"),
            ("contest_time", "contest_time_text"),
        ):
            if not rec.get(out_field):
                items = extracted.get(field) or []
                if items:
                    rec[out_field] = f"{items[0]['value']}｜原文：{items[0]['evidence'][:80]}"
        rec["_extracted"] = extracted

    stats["records_from_official"] = len(records)

    # 获奖新闻挂到对应赛事，作为"往届获奖情况"的可溯源证据
    attached = 0
    for n, entry in achievements:
        key = _entry_key(entry)
        rec = records.get(key)
        if rec is None:
            rec = {
                "key": key,
                "name": entry.name,
                "catalog_no": entry.no,
                "catalog_category": entry.category,
                "catalog_dept": entry.dept,
                "catalog_category_prev": None,
                "catalog_match_method": "catalog-title",
                "catalog_match_score": 1.0,
                "notices": [],
                "sources": [n.source_name],
                "official_links": [],
                "student_reviews": [],
                "registration_evidence": [],
                "achievements": [],
            }
            records[key] = rec
        rec.setdefault("achievements", []).append(
            {
                "title": n.title,
                "url": n.url,
                "published_at": n.published_at or n.list_date,
                "source_name": n.source_name,
            }
        )
        attached += 1
    stats["achievements_attached"] = attached

    log("[4/6] 主动发现通道检索")
    discovery: list[dict] = []
    if use_search and not offline:
        hits = collect_discovery(cfg, fetcher, stats=stats)
        stats["discovery_hits"] = len(hits)
        for h in hits:
            keep = _keep_discovery(h, cfg)
            h["kept"] = keep
            if not keep:
                discovery.append(h)
                continue
            guessed = guess_competition_name(h["title"])
            entry, score, method = catalog.match(guessed)
            h["catalog_category"] = entry.category if entry else None
            h["catalog_no"] = entry.no if entry else None
            discovery.append(h)
            real_url = h.get("real_url") or h["url"]
            if not _is_discoverable_competition(h["title"], real_url):
                h["kept"] = False
                continue
            # 云大自己的页面已经在官方栏目里采过了；这里只收计算机相关或已进目录的，
            # 避免体育学院/经济学院这类与专业无关的通知混进来。
            if (
                entry is None
                and "ynu.edu.cn" in (real_url or "")
                and not any(w in h["title"] for w in cfg.keywords["cs_signals"])
            ):
                h["kept"] = False
                continue
            if entry:
                key = _entry_key(entry)
                rec = records.get(key)
                if rec is None:
                    records[key] = {
                        "key": key,
                        "name": entry.name,
                        "catalog_no": entry.no,
                        "catalog_category": entry.category,
                        "catalog_dept": entry.dept,
                        "catalog_category_prev": None,
                        "catalog_match_method": method,
                        "catalog_match_score": score,
                        "notices": [],
                        "sources": ["搜索引擎发现"],
                        "official_links": [],
                        "student_reviews": [],
                        "registration_evidence": [],
                    }
                    rec = records[key]
            else:
                # 没进目录的赛事也先建记录，由云大生态评估决定是否值得纳入
                key = "name:" + (normalize_name(guessed) or normalize_name(h["title"]))
                rec = records.get(key)
                if rec is None:
                    records[key] = {
                        "key": key,
                        "name": guessed or h["title"],
                        "catalog_no": None,
                        "catalog_category": None,
                        "catalog_dept": None,
                        "catalog_category_prev": None,
                        "catalog_match_method": "miss",
                        "catalog_match_score": 0.0,
                        "notices": [],
                        "sources": ["搜索引擎发现"],
                        "official_links": [],
                        "student_reviews": [],
                        "registration_evidence": [],
                    }
                    rec = records[key]
            _append_notice(
                rec,
                {
                    "title": h["title"],
                    "url": real_url,
                    "source_id": "search360",
                    "source_name": "360搜索发现",
                    "authority": "aggregator",
                    "published_at": None,
                    "list_date": None,
                    "fetched_at": _now(),
                    "body_excerpt": h.get("snippet", ""),
                }
            )
        stats["discovery_kept"] = sum(1 for d in discovery if d.get("kept"))
    else:
        stats["discovery_hits"] = 0
        stats["discovery_kept"] = 0

    log("[5/6] 价值评估与分层（写入 SQLite）")
    store = Store(cfg.db_path)
    store.start_run()
    szcp = _load_szcp(cfg)
    szcp_rules = SzcpRules.load(cfg.szcp_college_path)
    if szcp_rules.available:
        log(f"      综测规则已加载：{szcp_rules.meta.get('title', '')}"
            f"（上限 {szcp_rules.rules.get('cap')} 分）")

    rep_cfg = cfg.settings.get("reputation", {}) or {}
    corpus = None
    engine_ok = True
    if rep_cfg.get("enabled", True):
        corpus = build_corpus(fetcher)
        engine_ok = engine_alive(fetcher)
        log(f"      校内证据库：{corpus.pages_ok} 个栏目页面已载入；"
            f"检索引擎{'可用' if engine_ok else '不可用'}")
    entries_by_no: dict[int, object] = {}
    for entry in list(catalog.entries) + list(catalog_prev.entries):
        entries_by_no.setdefault(entry.no, entry)
    profile_budget = int(rep_cfg.get("max_competitions", 40))
    profiles_done = 0

    changes: list[dict] = []
    new_count = 0
    push_count = 0
    for key, rec in records.items():
        rec["authority"] = (
            "official" if any(n["authority"] == "official" for n in rec["notices"])
            else "aggregator"
        )
        rec["published_latest"] = _first_nonempty(
            [n.get("published_at") or n.get("list_date") or "" for n in rec["notices"]][::-1]
        )
        prev = store.get_competition(key)
        if prev is None:
            rec["first_seen"] = _now()
            rec["is_new"] = True
            new_count += 1
            known_years: set[str] = set()
            prev_id = None
        else:
            rec["first_seen"] = prev["first_seen"]
            rec["is_new"] = False
            prev_id = int(prev["id"])
            known_years = store.notice_years(prev_id)
        known_years |= {(n.get("published_at") or "")[:4] for n in rec["notices"]}
        known_years = {y for y in known_years if len(y) == 4}
        rec["history_years"] = sorted(known_years)

        # ---- 云大生态评估：知名度 / 导师资源 / 获奖先例 ----
        cached_profile = None
        stale_profile = None
        if prev is not None and prev["profile_checked_at"] and prev["ynu_evidence"]:
            try:
                parsed = json.loads(prev["ynu_evidence"])
                age = datetime.now().astimezone() - datetime.fromisoformat(prev["profile_checked_at"])
                if (
                    age.days < int(rep_cfg.get("refresh_days", 30))
                    and parsed.get("version") == PROFILE_VERSION
                ):
                    cached_profile = parsed
                elif parsed.get("verdict") in ("sufficient", "inconclusive", "insufficient"):
                    # 版本升级/缓存过期时，先沿用旧结论，别让赛事因为没来得及重算就消失
                    stale_profile = parsed
            except (ValueError, json.JSONDecodeError):
                cached_profile = None

        if cached_profile:
            rec["ynu_profile"] = cached_profile
            rec["profile_checked_at"] = prev["profile_checked_at"]
        elif corpus is not None and profiles_done < profile_budget:
            entry = entries_by_no.get(rec.get("catalog_no")) if rec.get("catalog_no") else None
            profile = assess_ynu(rec, corpus, fetcher, entry, engine_ok=engine_ok)
            rec["ynu_profile"] = profile.as_dict()
            rec["profile_checked_at"] = _now()
            profiles_done += 1
            if profiles_done % 5 == 0:
                log(f"      云大生态评估进度：{profiles_done}/{min(len(records), profile_budget)}")
        elif stale_profile is not None:
            reused = dict(stale_profile)
            reused["stale"] = True
            reused.setdefault("notes", []).append("本轮额度不足，沿用上次评估结论")
            rec["ynu_profile"] = reused
            rec["profile_checked_at"] = prev["profile_checked_at"]
        else:
            rec["ynu_profile"] = {
                "verdict": "pending",
                "in_catalog": bool(rec.get("catalog_category")),
                "queries_run": 0,
                "search_ok": False,
                "notes": ["本轮额度不足，尚未检索；按「证据不充分」先纳入，下一轮补查"],
                "dimensions": [],
            }
            rec["profile_checked_at"] = None

        rec["ynu_verdict"] = rec["ynu_profile"]["verdict"]
        rec["visibility"] = (
            "excluded" if rec["ynu_verdict"] == "insufficient"
            else "included"
        )
        req = assess_requirement(rec)
        rec["requirement"] = req
        rec["mentor_dependency"] = req["mentor_dependency"]
        rec["difficulty"] = req["difficulty"]

        if rec["visibility"] == "excluded":
            rec["tier"] = "已排除"
            rec["tier_reason"] = "云大生态评估判定为不足：三个维度均无校内线索且不在认定目录中，暂不纳入"
            rec["score_total"] = None
            rec["verified_dimensions"] = 0
            rec["dimensions"] = []
            rec["risks"] = ["云大缺乏知名度、导师资源与获奖先例"]
            rec["next_actions"] = ["若确认校内有人组织或指导，可重新评估纳入"]
        else:
            evaluate(
                rec, cfg, catalog_meta, history_years=len(known_years),
                szcp=szcp, szcp_rules=szcp_rules,
            )
            rec["tier_reason"] = explain_tier(rec)

        rec_changes = _detect_changes(prev, rec)
        rec["last_changed"] = (
            _now() if rec_changes else (prev["last_changed"] if prev else None)
        )
        prev_notice_keys = store.existing_notice_keys(prev_id) if prev_id else set()

        comp_id = store.upsert_competition(
            rec, first_seen=rec["first_seen"], last_verified=_now()
        )
        for n in rec["notices"]:
            store.link(comp_id, store.upsert_notice(n), "notice")
        for achievement in rec.get("achievements", []):
            store.link(
                comp_id,
                store.upsert_notice(
                    {
                        "url": achievement["url"],
                        "title": achievement["title"],
                        "published_at": achievement.get("published_at"),
                        "source_id": "achievement",
                        "source_name": achievement.get("source_name"),
                        "authority": "official",
                    }
                ),
                "achievement",
            )
        for dim in rec["dimensions"]:
            store.add_valuation(comp_id, dim)
        for ch in rec_changes:
            ch.competition_id = comp_id
            store.add_change(ch)
            changes.append(
                {
                    "type": ch.change_type,
                    "name": ch.competition,
                    "field": ch.field,
                    "detail": ch.detail,
                }
            )
        if rec["visibility"] == "included":
            push_count += _queue_pushes(
                store, comp_id, rec, prev, rec_changes, prev_notice_keys,
                catalog_meta.get("title", "学校认定本科生学科竞赛目录"),
            )
        rec["last_verified"] = _now()

    stats["new_records"] = new_count
    included = [r for r in records.values() if r.get("visibility") == "included"]
    excluded = [r for r in records.values() if r.get("visibility") == "excluded"]
    pending = [r for r in records.values() if r.get("ynu_verdict") == "pending"]
    stats["records"] = len(included)
    stats["excluded"] = len(excluded)
    stats["pending_profiles"] = len(pending)
    stats["changes"] = len(changes)
    stats["pushes"] = push_count

    log("[6/6] 输出报告")
    stamp = date.today().isoformat()
    ordered = sorted(
        included,
        key=lambda r: (
            ["重点关注", "潜在机会", "低优先级/证据不足"].index(r["tier"]),
            -(r.get("score_total") or 0),
        ),
    )

    # 待推送提醒：只包含新赛事、临近截止和重要变化；已推送过的不会重复出现
    pending = store.pending_pushes()
    notify_path = cfg.outbox_dir / f"notifications-{stamp}.md"
    notify_path.write_text(render_notifications(pending), encoding="utf-8")
    delivery = dispatch(cfg, pending, log=log)
    push_ids = [int(row["id"]) for row in pending]
    if delivery.skipped or delivery.dry_run:
        # 内容已经落到 outbox 文件里就算"已消费"，避免以后真的开推送时把陈年积压一次性发出去
        store.mark_pushes(push_ids, status="dry-run", error=delivery.detail)
    elif delivery.ok:
        store.mark_pushes(push_ids, status="sent")
    else:
        store.mark_pushes(push_ids, status="pending", error=delivery.detail)
    stats["notifications"] = len(pending)
    stats["notification_file"] = str(notify_path)
    stats["delivery"] = {
        "channel": delivery.channel,
        "ok": delivery.ok,
        "detail": delivery.detail,
        "dry_run": delivery.dry_run,
    }
    stats["db"] = store.summary()
    stats["fetch_stats"] = fetcher.stats
    stats["szcp_verified"] = szcp_rules.available

    candidates = {
        "generated_at": _now(),
        "catalog": catalog_meta,
        "stats": stats,
        "fetch_log": log_rows,
        "changes": changes,
        "records": [_serializable(r) for r in ordered],
        "excluded": [_serializable(r) for r in excluded],
        "pending": [_serializable(r) for r in pending],
        "discovery": discovery,
    }
    cfg.candidates_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.candidates_path.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    digest = render_digest(ordered, discovery, stats, catalog_meta, changes)
    digest_path = cfg.outbox_dir / f"digest-{stamp}.md"
    digest_path.write_text(digest, encoding="utf-8")
    (cfg.outbox_dir / "digest-latest.md").write_text(digest, encoding="utf-8")

    cards_dir = cfg.outbox_dir / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    for stale in cards_dir.glob("*.md"):  # 清掉上一轮留下的旧信息卡，避免误导
        stale.unlink()
    card_paths = []
    for r in ordered:
        if r["tier"] != "重点关注":
            continue
        path = cards_dir / f"{_card_slug(r)}.md"
        path.write_text(render_card(r, catalog_meta), encoding="utf-8")
        card_paths.append(path)

    stats["digest"] = str(digest_path)
    stats["cards"] = [str(p) for p in card_paths]

    push_rows = [
        {
            "time": row["created_at"][:19],
            "type": row["push_type"],
            "title": row["title"],
            "status": row["status"],
        }
        for row in store.conn.execute(
            "SELECT * FROM push_log ORDER BY id DESC LIMIT 30"
        ).fetchall()
    ]
    payload = build_payload(ordered, discovery, stats, catalog_meta, changes, push_rows)
    dashboard_path = write_dashboard(cfg, payload)
    stats["dashboard"] = str(dashboard_path)

    store.finish_run(stats)
    db_summary = store.summary()
    store.close()
    log(f"      周报：{digest_path}")
    log(f"      信息卡：{len(card_paths)} 份 -> {cards_dir}")
    log(f"      仪表盘：{dashboard_path}")
    log(f"      提醒：{len(pending)} 条 -> {notify_path}")
    log(
        "      数据库：{competitions} 个赛事 / {notices} 条通知 / "
        "{changes} 处变化 / {pushes} 条提醒".format(**db_summary)
    )
    return candidates


def _card_slug(record: dict) -> str:
    from .report import _slug

    return _slug(record)


def _serializable(record: dict) -> dict:
    out = {k: v for k, v in record.items() if not k.startswith("_")}
    return out
