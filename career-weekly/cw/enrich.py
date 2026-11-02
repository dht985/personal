"""招聘/政策详情增强：只抽取原文明确出现的事实，并保存可变化内容快照。"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date
from urllib.parse import urljoin, urlsplit

import pdfplumber
from lxml import html as lxml_html

from .detail import CONTENT_XPATHS
from .net import Fetcher
from .store import Store

DATE_RE = re.compile(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?")
RANGE_RE = re.compile(
    r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?"
    r"[^。；]{0,20}(?:至|到|—|-)([^\d]{0,4})(\d{1,2})[月./-](\d{1,2})日"
)
DEADLINE_LABEL_RE = re.compile(
    r"报名时间|报名截止|简历截止|申请截止|投递截止|网申截止|"
    r"报名(?:日期|期限)|投递(?:日期|期限)"
)
LOCATION_RE = re.compile(
    r"(?:工作地点|工作城市|工作地址|办公地点)\s*[：:]\s*([^。；]{2,50})"
)
EDU_RE = re.compile(r"(?:博士|硕士|本科|大专)(?:研究生)?(?:学历)?(?:及以上|以上)?")
EMPLOYMENT_TERMS = ("校园招聘", "社会招聘", "实习生招聘", "实习")
TECH_TERMS = (
    "计算机科学与技术", "软件工程", "人工智能", "数据科学", "大数据",
    "计算机", "软件", "算法", "嵌入式", "网络安全", "信息安全",
    "工业软件", "自动化", "控制", "通信", "电子信息", "机器人",
    "仿真", "操作系统", "数据库", "云平台", "遥感", "地理信息",
)
APPLY_TERMS = ("立即申请", "在线报名", "网上报名", "投递简历", "申请职位", "招聘系统", "网申")
ATTACHMENT_TERMS = ("简章", "岗位表", "职位表", "招聘公告", "附件", "需求计划")
EXTRACTOR_VERSION = 2


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def content_digest(title: str, text: str, attachment_urls: list[str]) -> str:
    payload = "\n".join([title or "", normalize_text(text), *sorted(attachment_urls)])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso_date(year: int, month: int, day: int) -> str | None:
    value = f"{year}-{month:02d}-{day:02d}"
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def parse_deadline(text: str, published_at: str | None = None) -> dict | None:
    """返回原文中的截止日期片段；没有显式截止语义时返回空。"""
    text = text or ""
    range_match = RANGE_RE.search(text)
    if range_match and any(
        term in text[max(0, range_match.start() - 20):range_match.end() + 20]
        for term in ("报名", "截止", "投递", "申请")
    ):
        iso = _iso_date(
            int(range_match.group(1)), int(range_match.group(5)), int(range_match.group(6)),
        )
        if iso:
            snippet = text[max(0, range_match.start() - 30):range_match.end() + 15]
            return {"date": iso, "text": snippet.strip()[:120], "source": "date_range"}

    open_range = re.search(
        r"(?:报名|简历|申请|投递|网申)[^。；]{0,120}(?:至|到)\s*"
        + DATE_RE.pattern,
        text,
    )
    if open_range:
        date_match = DATE_RE.search(open_range.group(0))
        if date_match:
            iso = _iso_date(
                int(date_match.group(1)), int(date_match.group(2)),
                int(date_match.group(3)),
            )
            if iso:
                snippet = text[max(0, open_range.start() - 20):open_range.end() + 15]
                return {
                    "date": iso, "text": snippet.strip()[:120],
                    "source": "application_range",
                }

    for match in DEADLINE_LABEL_RE.finditer(text):
        context = text[max(0, match.start() - 10):match.start() + 240]
        dates = list(DATE_RE.finditer(context))
        if dates:
            chosen = dates[0]
            iso = _iso_date(
                int(chosen.group(1)), int(chosen.group(2)), int(chosen.group(3)),
            )
            if iso:
                return {
                    "date": iso, "text": context.strip()[:120],
                    "source": "application_context",
                }

    short = re.search(r"(\d{1,2})[月./-](\d{1,2})日?\s*(?:前|截止)", text)
    if short:
        year = int((published_at or "")[:4] or date.today().year)
        iso = _iso_date(year, int(short.group(1)), int(short.group(2)))
        if iso:
            snippet = text[max(0, short.start() - 30):short.end() + 15]
            return {
                "date": iso, "text": snippet.strip()[:120],
                "source": "inferred_year", "year_inferred": True,
            }
    return None


def extract_facts(title: str, text: str, links: list[dict], published_at: str | None) -> dict:
    combined = normalize_text(f"{title} {text}")
    deadline = parse_deadline(combined, published_at)
    locations = []
    for match in LOCATION_RE.finditer(combined):
        value = match.group(1).strip(" ，,。；")
        if value and value not in locations:
            locations.append(value[:50])
    education = []
    education_windows = []
    for marker in re.finditer(r"学历要求|任职资格|应聘条件|招聘条件", combined):
        education_windows.append(combined[marker.start():marker.start() + 220])
    explicit_edu = re.compile(r"(?:博士|硕士|本科)(?:研究生)?(?:学历)?(?:及以上|以上)")
    for window in education_windows:
        for value in EDU_RE.findall(window):
            if value not in education:
                education.append(value)
    if not education:
        education = list(dict.fromkeys(explicit_edu.findall(combined)))
    employment = [
        term for term in EMPLOYMENT_TERMS
        if term in title
    ]
    if not employment:
        employment = [term for term in EMPLOYMENT_TERMS if term in combined]
    technical = [term for term in TECH_TERMS if term in combined]
    apply_url = ""
    for link in links:
        label = f"{link.get('title', '')} {link.get('url', '')}".lower()
        if any(term.lower() in label for term in APPLY_TERMS):
            apply_url = link["url"]
            break
    facts = {
        "employment_type": employment,
        "education": education,
        "technical_terms": technical[:12],
        "locations": locations[:4],
        "deadline": deadline,
        "apply_url": apply_url,
        "published_at": published_at,
    }
    return {key: value for key, value in facts.items() if value not in (None, "", [])}


def _attachment_links(links: list[dict]) -> list[dict]:
    out = []
    for link in links:
        title = link.get("title", "")
        label = f"{title} {link.get('url', '')}"
        if not _is_pdf(link["url"]):
            continue
        if not any(term in label for term in ATTACHMENT_TERMS):
            continue
        out.append(link)
    return out[:3]


def _page_content(raw: str, base_url: str, title: str) -> tuple[str, list[dict]]:
    doc = lxml_html.fromstring(raw)
    for bad in doc.xpath("//script|//style|//noscript|//nav|//footer|//header"):
        bad.getparent().remove(bad)
    title_nodes = [
        node for node in doc.xpath(
            "//*[normalize-space(text()) = normalize-space($title)]",
            title=title,
        )
        if normalize_text(node.text_content() or "") == title
    ]
    node = title_nodes[-1] if title_nodes else None
    for _ in range(8):
        if node is None or node.getparent() is None:
            break
        node = node.getparent()
        marker = f"{node.get('class', '')} {node.get('id', '')}".lower()
        text_length = len(normalize_text(node.text_content() or ""))
        if text_length >= 100 and any(
            term in marker for term in ("content", "article", "detail", "main")
        ):
            break
    if node is not None and len(normalize_text(node.text_content() or "")) >= 100:
        best = normalize_text(node.text_content() or "")
    else:
        best = ""
        for xpath in CONTENT_XPATHS:
            for candidate in doc.xpath(xpath):
                text = normalize_text(candidate.text_content() or "")
                if len(text) > len(best):
                    best = text
        if len(best) < 120:
            best = normalize_text(doc.text_content() or "")
    title_pos = best.find(title)
    if title_pos >= 0:
        best = best[title_pos + len(title):]
    stop_re = re.compile(r"联系我们|版权声明|友情链接|成员单位网站|上一篇|下一篇|相关新闻")
    stop = stop_re.search(best)
    if stop:
        best = best[:stop.start()]
    best = best.strip(" -|")
    links = []
    seen = set()
    for anchor in doc.xpath("//a[@href]"):
        href = (anchor.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:")):
            continue
        url = urljoin(base_url, href).split("#")[0]
        if url in seen or urlsplit(url).scheme not in ("http", "https"):
            continue
        seen.add(url)
        links.append({
            "title": normalize_text(anchor.text_content() or ""),
            "url": url,
        })
    return best[:20000], links


def _is_pdf(url: str, content_type: str = "") -> bool:
    return "application/pdf" in (content_type or "").lower() or urlsplit(url).path.lower().endswith(".pdf")


def _pdf_text(content: bytes, max_pages: int = 20) -> str:
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages[:max_pages])
    return normalize_text(text)[:30000]




def enrich_item(fetcher: Fetcher, item: dict) -> dict | None:
    """抓取公告详情和至多 3 个 PDF 附件，返回原文事实与摘要。"""
    url = item.get("url", "")
    if not url.startswith(("http://", "https://")):
        return None
    errors: list[str] = []
    links: list[dict] = []
    if _is_pdf(url):
        binary = fetcher.get_bytes(url)
        if not binary.ok:
            return {"error": binary.error or f"HTTP {binary.status}"}
        try:
            text = _pdf_text(binary.content)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"PDF 解析失败：{type(exc).__name__}"}
        attachments = [{"title": item["title"], "url": url}]
    else:
        page = fetcher.get(url)
        if not page.ok:
            return {"error": page.error or f"HTTP {page.status}"}
        text, links = _page_content(page.text, page.final_url, item["title"])
        if not text:
            return {"error": "正文为空"}
        attachments = _attachment_links(links)
        pdf_texts = []
        for attachment in attachments:
            binary = fetcher.get_bytes(attachment["url"])
            if not binary.ok:
                errors.append(f"附件失败：{attachment['title'][:20]}")
                continue
            try:
                extract = _pdf_text(binary.content)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"PDF 解析失败：{type(exc).__name__}")
                continue
            if extract:
                pdf_texts.append(f"[附件 {attachment['title']}] {extract}")
        if pdf_texts:
            text = normalize_text(text + " " + " ".join(pdf_texts))[:40000]
    facts = extract_facts(
        item["title"], text, links + attachments, item.get("published_at"),
    )
    facts["attachments"] = attachments
    if errors:
        facts["extraction_errors"] = errors
    return {
        "content_hash": content_digest(
            item["title"], text, [attachment["url"] for attachment in attachments],
        ),
        "detail_excerpt": text[:3500],
        "facts": facts,
    }


def enrich_items(
    fetcher: Fetcher, items: list[dict], store: Store,
    max_items: int = 24, log=print,
) -> dict[str, int]:
    """只增强招聘和政策条目；正文变化写入快照表。"""
    candidates = [
        item for item in items
        if item.get("source_purpose") in {"recruit", "policy"}
        and item.get("source_id") and not item["source_id"].startswith("manual-")
    ]
    candidates.sort(key=lambda item: item.get("published_at") or "", reverse=True)
    candidates.sort(
        key=lambda item: (
            item.get("source_purpose") != "recruit",
            not item.get("is_new"),
        )
    )
    stats = {"attempted": 0, "succeeded": 0, "failed": 0, "changed": 0}
    for item in candidates[:max_items]:
        stats["attempted"] += 1
        result = enrich_item(fetcher, item)
        if not result or result.get("error"):
            stats["failed"] += 1
            item["detail_error"] = (result or {}).get("error", "未取得正文")
            continue
        saved = store.update_content(
            item["url"], result["content_hash"], result["detail_excerpt"],
            result["facts"], extractor_version=EXTRACTOR_VERSION,
        )
        if not saved.get("saved"):
            stats["failed"] += 1
            continue
        stats["succeeded"] += 1
        if saved.get("changed"):
            stats["changed"] += 1
        item["content_changed"] = bool(saved.get("changed"))
        item["detail_excerpt"] = result["detail_excerpt"]
        item["facts"] = result["facts"]
    log(
        f"  详情增强：成功 {stats['succeeded']}/{stats['attempted']}，"
        f"内容变化 {stats['changed']}"
    )
    return stats
