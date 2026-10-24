"""采集通道：官方栏目直采 + 搜索引擎主动发现。"""

from __future__ import annotations

import re
import hashlib
import json
import os
import urllib.parse
from datetime import datetime, timedelta
from dataclasses import dataclass, field

import requests
from lxml import html as lxml_html

from .config import Config
from .net import Fetcher
from .parse import parse_detail_page, parse_list_page
from .textutil import canonical_url, clean_text

SEARCH_ENDPOINT = "https://www.so.com/s"
SOGOU_ENDPOINT = "https://www.sogou.com/web"
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


class SearchBlocked(Exception):
    """搜索引擎返回验证码/反爬页，结果不可信。"""


_SERPAPI_DOWN = False  # 一旦额度用完/鉴权失败，本轮不再反复重试
_CALLS_THIS_RUN = 0    # 本轮已消耗的真实 API 调用次数（命中缓存不计）


def reset_api_budget() -> None:
    global _CALLS_THIS_RUN, _SERPAPI_DOWN
    _CALLS_THIS_RUN = 0
    _SERPAPI_DOWN = False


@dataclass
class Notice:
    source_id: str
    source_name: str
    authority: str
    scope: str
    url: str
    title: str
    list_date: str | None = None
    published_at: str | None = None
    body: str = ""
    external_links: list = field(default_factory=list)
    attachments: list = field(default_factory=list)
    fetched_at: str = ""
    from_cache: bool = False

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "authority": self.authority,
            "scope": self.scope,
            "url": self.url,
            "title": self.title,
            "list_date": self.list_date,
            "published_at": self.published_at,
            "body_len": len(self.body or ""),
            "external_links": self.external_links,
            "attachments": self.attachments,
            "fetched_at": self.fetched_at,
            "from_cache": self.from_cache,
        }


OWN_HOSTS = {
    "jwc.ynu.edu.cn", "www.jwc.ynu.edu.cn", "sei.ynu.edu.cn", "www.sei.ynu.edu.cn",
    "ynu.edu.cn", "www.ynu.edu.cn", "cahe.edu.cn", "www.cahe.edu.cn",
}

# 页脚友情链接一类的导航地址，不是赛事官网，不应出现在"官方入口"里
LINK_FILTER = {
    "own_suffixes": ["ynu.edu.cn", "cahe.edu.cn"],
    "blacklist_hosts": [
        "moe.gov.cn", "eqea.edu.cn", "ynjy.cn", "ynzs.cn", "hep.com.cn",
        "chsi.com.cn", "cnki.net",
    ],
}


def collect_official(cfg: Config, fetcher: Fetcher) -> tuple[list[Notice], list[dict]]:
    """直采官方栏目。返回 (通知列表, 采集日志)。"""
    notices: list[Notice] = []
    log_rows: list[dict] = []
    seen_urls: set[str] = set()

    for src in cfg.sources:
        list_urls = list(src["list_urls"])
        # 栏目分页：先从首个列表页里找出最大页码，再往前翻 max_pages-1 页
        pag = src.get("pagination")
        if pag:
            first = fetcher.fetch(list_urls[0])
            if first.ok:
                nums = [int(n) for n in re.findall(pag["discover"], first.text)]
                if nums:
                    top = max(nums)
                    for offset in range(1, pag.get("max_pages", 2)):
                        page = top - offset + 1
                        if page < 1:
                            break
                        list_urls.append(pag["url_template"].format(page=page))
        for list_url in list_urls:
            res = fetcher.fetch(list_url)
            row = {
                "source": src["id"],
                "list_url": list_url,
                "status": res.status,
                "error": res.error,
                "from_cache": res.from_cache,
                "items": 0,
            }
            if not res.ok:
                log_rows.append(row)
                continue
            items = parse_list_page(res.text, res.final_url, src["item_regex"])
            row["items"] = len(items)
            log_rows.append(row)
            for it in items:
                if canonical_url(it["url"]) in seen_urls:
                    continue
                seen_urls.add(canonical_url(it["url"]))
                notices.append(
                    Notice(
                        source_id=src["id"],
                        source_name=src["name"],
                        authority=src["authority"],
                        scope=src.get("scope", ""),
                        url=it["url"],
                        title=it["title"],
                        list_date=it.get("list_date"),
                        fetched_at=res.fetched_at,
                    )
                )
    return notices, log_rows


def enrich_details(
    cfg: Config, fetcher: Fetcher, notices: list[Notice], limit: int | None = None
) -> int:
    """抓取通知详情页并填充标题/正文/发布时间/外链/附件。返回抓取条数。"""
    limit = limit or cfg.settings["run"]["detail_limit"]
    done = 0
    for n in notices:
        if done >= limit:
            break
        res = fetcher.fetch(n.url)
        done += 1
        if not res.ok or not res.text:
            continue
        parsed = parse_detail_page(res.text, n.url, OWN_HOSTS, LINK_FILTER)
        if parsed["title"] and len(parsed["title"]) >= len(n.title or ""):
            n.title = parsed["title"]
        n.body = parsed["body"]
        n.published_at = parsed["published_at"] or n.list_date
        n.external_links = parsed["external_links"]
        n.attachments = parsed["attachments"]
        n.fetched_at = res.fetched_at
        n.from_cache = res.from_cache
    return done


_META_REFRESH = re.compile(
    r"""<meta[^>]+http-equiv=["']?refresh["']?[^>]+content=["'][^"']*?url=([^"'>]+)""",
    re.IGNORECASE,
)


def resolve_redirect(fetcher: Fetcher, url: str) -> str:
    """360 搜索结果为 /link?m=... 跳转页，真实地址写在 meta refresh 中。"""
    if "so.com/link" not in url:
        return url
    res = fetcher.fetch(url, check_robots=False)
    if not res.ok or not res.text:
        return url
    m = _META_REFRESH.search(res.text)
    if m:
        target = m.group(1).strip().strip("'\"")
        if target.startswith("//"):
            target = "https:" + target
        return target
    m2 = re.search(r"""URL=['"]([^'"]+)['"]""", res.text)
    return m2.group(1) if m2 else url


def search_360(fetcher: Fetcher, query: str, pages: int = 1) -> list[dict]:
    out: list[dict] = []
    for pn in range(1, pages + 1):
        params = {"q": query}
        if pn > 1:
            params["pn"] = str(pn)
        url = SEARCH_ENDPOINT + "?" + urllib.parse.urlencode(params)
        res = fetcher.fetch(url, check_robots=False)
        if not res.ok or not res.text:
            break
        if "qcaptcha" in (res.final_url or "") or "访问异常" in res.text:
            raise SearchBlocked("360 返回验证码页面")
        doc = lxml_html.fromstring(res.text)
        blocks = doc.xpath("//li[contains(@class,'res-list')]")
        if not blocks:
            break
        for li in blocks:
            anchors = li.xpath(".//h3[contains(@class,'res-title')]/a")
            if not anchors:
                continue
            href = anchors[0].get("href") or ""
            title = re.sub(r"<[^>]+>", "", clean_text(anchors[0].text_content() or ""))
            desc = li.xpath(".//*[contains(@class,'res-desc') or contains(@class,'res-richtext')]")
            snippet = clean_text(desc[0].text_content() or "") if desc else ""
            out.append(
                {
                    "title": title,
                    "url": href,
                    "snippet": snippet[:220],
                    "engine": "360",
                    "query": query,
                }
            )
    return out


def search_sogou(fetcher: Fetcher, query: str, pages: int = 1) -> list[dict]:
    """搜狗网页搜索。360 被限流时作为主引擎使用。"""
    out: list[dict] = []
    for page in range(1, pages + 1):
        params = {"query": query}
        if page > 1:
            params["page"] = str(page)
        url = SOGOU_ENDPOINT + "?" + urllib.parse.urlencode(params)
        res = fetcher.fetch(url, check_robots=False)
        if not res.ok or not res.text:
            break
        if "antispider" in (res.final_url or "") or "antispider" in res.text:
            raise SearchBlocked("搜狗返回反爬验证页")
        doc = lxml_html.fromstring(res.text)
        blocks = doc.xpath("//div[contains(@class,'vrwrap')]")
        if not blocks:
            break
        for block in blocks:
            anchors = block.xpath(".//h3/a")
            if not anchors:
                continue
            href = anchors[0].get("href") or ""
            title = clean_text(anchors[0].text_content() or "")
            if not title:
                continue
            full = urllib.parse.urljoin("https://www.sogou.com/", href)
            text = clean_text(block.text_content() or "")
            snippet = text[len(title):][:220] if text.startswith(title) else text[:220]
            out.append(
                {
                    "title": title,
                    "url": full,
                    "snippet": snippet,
                    "engine": "sogou",
                    "query": query,
                }
            )
    return out


def resolve_sogou(fetcher: Fetcher, url: str) -> str:
    """搜狗结果通常是 /link?url=... 跳转，取最终地址。"""
    if "sogou.com/link" not in url:
        return url
    res = fetcher.fetch(url, check_robots=False)
    return res.final_url if res.ok else url


def _api_cache_path(fetcher: Fetcher, key: str):
    cache_dir = fetcher.cfg.raw_dir / "api_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.json"


def search_serpapi(
    fetcher: Fetcher, query: str, pages: int = 1, engine: str = "baidu",
    ttl_hours: float | None = None,
) -> tuple[list[dict], bool]:
    """SerpApi 结构化搜索。

    刻意不走 Fetcher.fetch：它的原始快照会把完整 URL 存进 data/raw，
    而 URL 里带着 api_key，会泄露密钥。这里只把结果按"引擎+查询"缓存。
    """
    global _SERPAPI_DOWN
    global _CALLS_THIS_RUN
    if _SERPAPI_DOWN:
        return [], False
    search_cfg = (fetcher.cfg.settings.get("search") or {})
    env_name = search_cfg.get("key_env", "COMPRADAR_SERPAPI_KEY")
    key = (os.environ.get(env_name) or "").strip()
    if not key:
        return [], False

    cache_path = _api_cache_path(fetcher, f"{engine}|{query}|{pages}")
    if ttl_hours is None:
        ttl_hours = float(search_cfg.get("cache_hours", 6))
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            age = datetime.now().astimezone() - datetime.fromisoformat(cached["fetched_at"])
            if age <= timedelta(hours=ttl_hours):
                return cached.get("results", []), True
        except (ValueError, KeyError, json.JSONDecodeError):
            pass

    # 免费档 50 次/小时，留出余量，避免一轮把整小时额度用完
    budget = int(search_cfg.get("max_calls_per_run", 45))
    if _CALLS_THIS_RUN >= budget:
        return [], False

    params = {
        "engine": engine,
        "q": query,
        "num": int(search_cfg.get("num_results", 10)),
        "api_key": key,
    }
    try:
        resp = requests.get(SERPAPI_ENDPOINT, params=params, timeout=40)
        _CALLS_THIS_RUN += 1
        if resp.status_code in (401, 402, 429):
            _SERPAPI_DOWN = True
            return [], False
        if resp.status_code != 200:
            return [], False
        data = resp.json()
    except Exception:  # noqa: BLE001
        return [], False
    if data.get("error"):
        _SERPAPI_DOWN = True
        return [], False

    results: list[dict] = []
    for item in data.get("organic_results", []):
        link = item.get("link") or ""
        title = clean_text(item.get("title") or "")
        if not link or not title:
            continue
        results.append(
            {
                "title": title,
                "url": link,
                "snippet": clean_text(item.get("snippet") or item.get("abstract") or "")[:240],
                "engine": f"serpapi-{engine}",
                "query": query,
            }
        )
    cache_path.write_text(
        json.dumps(
            {"query": query, "engine": engine, "fetched_at": _now_iso(), "results": results},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return results, True


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def search_web(
    fetcher: Fetcher, query: str, pages: int = 1, ttl_hours: float | None = None
) -> tuple[list[dict], str, bool]:
    """统一检索入口：优先结构化 API，其次公开引擎兜底。

    返回 (结果, 实际使用的引擎, 本次检索是否可信)。公开引擎命中验证码页时
    会抛 SearchBlocked，这里转成 ok=False，避免把"被拦"当成"没结果"。
    """
    search_cfg = fetcher.cfg.settings.get("search") or {}
    provider = search_cfg.get("provider", "serpapi")
    engine = search_cfg.get("engine", "baidu")

    if provider == "serpapi":
        results, ok = search_serpapi(fetcher, query, pages, engine, ttl_hours)
        if ok:
            return results, f"serpapi-{engine}", True
        if _SERPAPI_DOWN:
            return [], "serpapi-down", False

    for name, fn in (("sogou", search_sogou), ("360", search_360)):
        try:
            results = fn(fetcher, query, pages)
        except SearchBlocked:
            continue
        except Exception:  # noqa: BLE001
            continue
        if results:
            return results, name, True
    return [], "none", False


def collect_discovery(
    cfg: Config, fetcher: Fetcher, resolve: bool = True, stats: dict | None = None
) -> list[dict]:
    """跑检索式，发现新赛事/新通知，并还原真实链接。"""
    queries = cfg.keywords.get("discovery", {}).get("query", [])
    pages = cfg.settings["run"].get("search_pages", 1)
    seen: set[str] = set()
    results: list[dict] = []
    engines_used: dict[str, int] = {}
    blocked = 0
    for q in queries:
        hits, engine, ok = search_web(fetcher, q["q"], pages)
        if not ok:
            blocked += 1
            continue
        engines_used[engine] = engines_used.get(engine, 0) + 1
        for h in hits:
            if h["title"] in seen:
                continue
            seen.add(h["title"])
            h["intent"] = q.get("intent", "")
            h["real_url"] = (
                resolve_redirect(fetcher, h["url"]) if (resolve and "so.com/link" in h["url"])
                else resolve_sogou(fetcher, h["url"]) if (resolve and "sogou.com/link" in h["url"])
                else h["url"]
            )
            results.append(h)
    if stats is not None:
        stats["discovery_engines"] = engines_used
        stats["discovery_blocked_queries"] = blocked
        stats["discovery_complete"] = blocked == 0
    return results
