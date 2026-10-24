"""云大生态评估：一项赛事在云大（尤其信息学院）的知名度、导师资源、获奖先例。

判定规则（与需求一致，偏保守）：
- 充足      ：有明确校内支撑证据（在认定目录里，或三维度中至少两个有据）
- 证据不充分：只找到零星线索，或检索受限无法下结论  -> 仍然纳入
- 不足      ：三个维度都没有任何校内线索，且检索正常完成、且不在认定目录里 -> 不纳入

注意"没搜到"不等于"不存在"，所以只有检索确实跑完、且完全没有线索时才判不足；
检索失败一律按证据不充分处理，避免因为网络问题误杀赛事。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .config import Config
from .net import Fetcher
from .sources import resolve_redirect, resolve_sogou, search_web
from .textutil import clean_text, normalize_name

YNU_SUFFIXES = ("ynu.edu.cn",)
# 评估逻辑变化时递增，旧缓存会自动失效重算
PROFILE_VERSION = 7
COMMUNITY_HOSTS = (
    "zhihu.com", "tieba.baidu.com", "csdn.net", "jianshu.com", "douban.com",
    "xiaohongshu.com", "bilibili.com", "weibo.com", "mp.weixin.qq.com",
)

# 信息学院/软件学院里固定会提到赛事组织的页面
CORPUS_PAGES = [
    ("https://www.ise.ynu.edu.cn/directory/75/", "信息学院竞赛概况"),
    ("https://www.ise.ynu.edu.cn/directory/77/", "信息学院竞赛动态"),
    ("https://www.ise.ynu.edu.cn/news-list/14/", "信息学院竞赛通知"),
    ("https://www.ise.ynu.edu.cn/news-list/6/", "信息学院新闻动态"),
    ("http://syzx.ise.ynu.edu.cn/sfyl/cbjs.htm", "信息学院实验中心承办竞赛"),
    ("http://www.sei.ynu.edu.cn/xwgg/xyxw.htm", "软件学院学院新闻"),
]

AWARD_RE = re.compile(r"获奖|斩获|荣获|佳绩|喜报|一等奖|二等奖|三等奖|金奖|银奖|铜奖|夺冠|夺魁|优异")
MENTOR_RE = re.compile(r"指导教师|指导老师|指导团队|教练|带队|导师")
ORG_RE = re.compile(r"组织并参加|组织参加|组织计算机")
YNU_HINT_RE = re.compile(r"云南大学|云大|ynu", re.IGNORECASE)


@dataclass
class Evidence:
    title: str
    url: str
    snippet: str
    source: str

    def as_dict(self) -> dict:
        return {"title": self.title, "url": self.url,
                "snippet": self.snippet, "source": self.source}


@dataclass
class Dimension:
    key: str
    label: str
    status: str          # found | none
    evidence: list[Evidence] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "status": self.status,
                "evidence": [e.as_dict() for e in self.evidence]}


@dataclass
class Profile:
    verdict: str                 # sufficient | inconclusive | insufficient
    in_catalog: bool
    dimensions: list[Dimension]
    queries_run: int = 0
    search_ok: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def included(self) -> bool:
        return self.verdict != "insufficient"

    def as_dict(self) -> dict:
        return {
            "version": PROFILE_VERSION,
            "verdict": self.verdict,
            "in_catalog": self.in_catalog,
            "queries_run": self.queries_run,
            "search_ok": self.search_ok,
            "notes": self.notes,
            "dimensions": [d.as_dict() for d in self.dimensions],
        }


def _host(url: str) -> str:
    return urlsplit(url or "").netloc.lower()


def is_ynu(url: str) -> bool:
    host = _host(url)
    return any(host == s or host.endswith("." + s) for s in YNU_SUFFIXES)


def is_community(url: str) -> bool:
    host = _host(url)
    return any(host == s or host.endswith("." + s) for s in COMMUNITY_HOSTS)


_AFFIX_PREFIX = ("全国大学生", "中国大学生", "全国高校", "全国", "中国", "国际")
_AFFIX_SUFFIX = ("大赛", "竞赛", "比赛", "挑战赛", "赛事")


def _core(name: str) -> str:
    s = normalize_name(name)
    for p in _AFFIX_PREFIX:
        if s.startswith(p):
            s = s[len(p):]
            break
    for q in _AFFIX_SUFFIX:
        if s.endswith(q):
            s = s[: -len(q)]
            break
    return s


def _mention_window(text: str, name: str, pad: int = 50) -> str | None:
    """在文本里找赛事名，返回命中位置附近的片段（而不是整段文本）。

    先找完整名称；找不到再找去掉通用前后缀的核心词，且核心词至少 5 个字，
    避免"设计大赛""人工智能"这类通用词命中整篇新闻造成假阳性。
    """
    norm = normalize_name(text)
    target = normalize_name(name)
    if not target:
        return None
    pos = norm.find(target)
    if pos < 0:
        core = _core(name)
        if len(core) >= 5:
            pos = norm.find(core)
    if pos < 0:
        return None
    return norm[max(0, pos - pad): pos + pad * 2]


class Corpus:
    """校内证据库：把几个学院栏目抓下来，供所有赛事共享匹配。"""

    def __init__(self) -> None:
        self.items: list[Evidence] = []
        self.pages_ok = 0

    def add_page(self, name: str, url: str, text: str) -> None:
        self.items.append(Evidence(title=name, url=url, snippet=text[:6000], source=name))

    def match(self, name: str) -> list[Evidence]:
        hits: list[Evidence] = []
        for item in self.items:
            window = _mention_window(item.snippet + " " + item.title, name)
            if window:
                hits.append(
                    Evidence(item.title, item.url, window, item.source)
                )
        return hits


def build_corpus(fetcher: Fetcher) -> Corpus:
    corpus = Corpus()
    for url, label in CORPUS_PAGES:
        res = fetcher.fetch(url)
        if not res.ok or not res.text:
            continue
        from lxml import html as lxml_html

        doc = lxml_html.fromstring(res.text)
        for bad in doc.xpath("//script|//style|//noscript"):
            bad.getparent().remove(bad)
        text = clean_text(doc.text_content() or "")
        if text:
            corpus.add_page(label, res.final_url or url, text)
            corpus.pages_ok += 1
    return corpus


def queries_for(name: str) -> list[str]:
    """两查询策略：一条查云大层面的存在感，一条同时收获奖与指导教师线索。

    每条都要花一次 API 额度（免费档 250 次/月），所以不做无谓的拆分。
    """
    return [
        f"云南大学 {name}",
        f"云南大学 {name} 获奖 指导教师",
    ]


def engine_alive(fetcher: Fetcher) -> bool:
    """用一条必然有结果的通用查询确认搜索引擎可用（搜狗优先，360 备用）。

    360 对过于具体的查询会返回 0 条，那是"确实没有结果"，不能当成检索失败。
    """
    try:
        results, _engine, ok = search_web(fetcher, "云南大学 信息学院 全国大学生竞赛", pages=1)
        return ok and bool(results)
    except Exception:  # noqa: BLE001
        return False


def _collect_search(
    fetcher: Fetcher, name: str, max_results: int = 10, max_resolve: int = 8
) -> tuple[list[dict], bool, int, int]:
    """跑定向检索并还原真实链接。返回 (结果, 检索是否正常完成, 跳过条数, 实际完成查询数)。

    360 的跳转链接必须先请求一次才能知道真实域名。为了不给外校结果白白发请求，
    先看标题/摘要里有没有"云大"线索，没有的直接跳过（会牺牲极少数标题不含校名的结果）。
    """
    hits: list[dict] = []
    ok_any = False
    skipped = 0
    resolved = 0
    queries_ok = 0
    for q in queries_for(name):
        try:
            results, _engine, ok = search_web(fetcher, q, pages=1, ttl_hours=24 * 30)
        except Exception:  # noqa: BLE001
            results, ok = [], False
        if not ok:
            continue
        queries_ok += 1
        if results:
            ok_any = True
        for item in results[:5]:
            url = item.get("url") or ""
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            if "so.com/link" in url:
                if not (YNU_HINT_RE.search(title) or YNU_HINT_RE.search(snippet)):
                    skipped += 1
                    continue
                if resolved >= max_resolve:
                    skipped += 1
                    continue
                url = resolve_redirect(fetcher, url)
                resolved += 1
            elif "sogou.com/link" in url:
                if not (YNU_HINT_RE.search(title) or YNU_HINT_RE.search(snippet)):
                    skipped += 1
                    continue
                if resolved >= max_resolve:
                    skipped += 1
                    continue
                url = resolve_sogou(fetcher, url)
                resolved += 1
            hits.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "query": q,
                }
            )
            if len(hits) >= max_results:
                return hits, ok_any, skipped, queries_ok
    return hits, ok_any, skipped, queries_ok


def assess(
    record: dict,
    corpus: Corpus,
    fetcher: Fetcher,
    catalog_entry,
    *,
    do_search: bool = True,
    cached: dict | None = None,
    engine_ok: bool = True,
) -> Profile:
    name = record["name"]
    in_catalog = catalog_entry is not None
    dims = {
        "awareness": Dimension("awareness", "云大知名度", "none"),
        "mentor": Dimension("mentor", "导师指导资源", "none"),
        "awards": Dimension("awards", "获奖先例", "none"),
    }
    notes: list[str] = []

    # 1) 校内证据库
    for hit in corpus.match(name):
        text = hit.title + " " + hit.snippet
        ev = Evidence(hit.title, hit.url, hit.snippet[:200], hit.source)
        dims["awareness"].evidence.append(ev)
        if AWARD_RE.search(text):
            dims["awards"].evidence.append(ev)
        if MENTOR_RE.search(text) or ORG_RE.search(text):
            dims["mentor"].evidence.append(ev)

    # 2) 认定目录本身就是校内支撑：有承办学院和竞赛负责人
    if catalog_entry is not None:
        detail = f"《学校认定本科生学科竞赛目录（2026版）》第 {catalog_entry.no} 项，" \
                 f"承办单位 {catalog_entry.dept or '未标注'}"
        if catalog_entry.owner:
            detail += f"，竞赛负责人 {catalog_entry.owner}"
        ev = Evidence("认定目录条目", "", detail, "catalog")
        dims["awareness"].evidence.append(ev)
        if catalog_entry.owner:
            dims["mentor"].evidence.append(ev)

    # 3) 赛事自身的通知：如果本来就发在云大官网上，这本身就是"云大知道它"的硬证据
    for notice in record.get("notices", []):
        url = notice.get("url") or ""
        if not is_ynu(url):
            continue
        text = (notice.get("title") or "") + " " + (notice.get("body_excerpt") or "")
        window = _mention_window(text, name) or text[:240]
        ev = Evidence(notice.get("title") or "校内通知", url, window[:240], "校内通知")
        dims["awareness"].evidence.append(ev)
        if AWARD_RE.search(window):
            dims["awards"].evidence.append(ev)
        if MENTOR_RE.search(window):
            dims["mentor"].evidence.append(ev)

    # 4) 定向检索
    search_ok = True
    queries_run = 0
    if cached is not None:
        for key, items in (cached.get("dimensions") or {}).items():
            if key in dims:
                dims[key].evidence.extend(
                    Evidence(e["title"], e["url"], e["snippet"], e["source"]) for e in items
                )
        queries_run = cached.get("queries_run", 0)
        search_ok = cached.get("search_ok", True)
    elif do_search:
        hits, ok_any, skipped, queries_ok = _collect_search(fetcher, name)
        # 有结果说明引擎正常；没结果时用 canary 结果判定"确实没有"还是"检索挂了"
        search_ok = ok_any or engine_ok
        queries_run = queries_ok
        if skipped:
            notes.append(f"另有 {skipped} 条结果因标题/摘要无云大线索未展开（外校结果居多）")
        for hit in hits:
            url = hit["url"]
            if not is_ynu(url) and not is_community(url):
                continue  # 外校通知不能当作云大证据
            text = hit["title"] + " " + hit["snippet"]
            window = _mention_window(text, name)
            if not window:
                continue
            source = "云大官网" if is_ynu(url) else "学生/社区讨论"
            ev = Evidence(hit["title"], url, window[:240], source)
            dims["awareness"].evidence.append(ev)
            if AWARD_RE.search(window) and is_ynu(url):
                dims["awards"].evidence.append(ev)
            if MENTOR_RE.search(window) and is_ynu(url):
                dims["mentor"].evidence.append(ev)

    # 去重并判定
    for dim in dims.values():
        seen, uniq = set(), []
        for ev in dim.evidence:
            key = (ev.url, ev.title)
            if key in seen:
                continue
            seen.add(key)
            uniq.append(ev)
        dim.evidence = uniq[:5]
        dim.status = "found" if dim.evidence else "none"

    found = sum(1 for d in dims.values() if d.status == "found")
    if in_catalog:
        verdict = "sufficient"
        notes.append("已列入学校认定目录，承办学院与负责人明确")
    elif found >= 2:
        verdict = "sufficient"
        notes.append(f"校内有据可查的维度 {found}/3")
    elif found == 1:
        verdict = "inconclusive"
        notes.append("只找到零星校内线索，证据不充分，仍纳入观察")
    elif not search_ok:
        verdict = "inconclusive"
        notes.append("定向检索未正常返回，无法下结论，仍纳入观察")
    else:
        verdict = "insufficient"
        notes.append("三个维度均未找到任何校内线索，且不在认定目录中")

    return Profile(
        verdict=verdict,
        in_catalog=in_catalog,
        dimensions=[dims["awareness"], dims["mentor"], dims["awards"]],
        queries_run=queries_run,
        search_ok=search_ok,
        notes=notes,
    )
