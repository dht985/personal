"""附件文本提取：PDF、DOCX、XLSX。

只提取可复制的文本层，不执行宏、不解析旧版二进制 Office 文件。
扫描版 PDF 没有文本层时明确返回错误，交给人工核对。
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

import pdfplumber

from .net import Fetcher
from .textutil import clean_text

MAX_ATTACHMENTS = 4
MAX_TEXT_CHARS = 30000
MAX_PDF_PAGES = 30
PRIORITY_TERMS = ("招聘", "通知", "简章", "规则", "章程", "岗位", "日程", "安排", "报名")
UNSUPPORTED_SUFFIXES = {".doc", ".xls", ".zip", ".rar", ".7z"}


def _kind(url: str, filename: str, content: bytes) -> str:
    if content.startswith(b"%PDF"):
        return "pdf"
    if content.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(content)).namelist()
        except zipfile.BadZipFile:
            return "unknown"
        if any(name.startswith("word/") for name in names):
            return "docx"
        if any(name.startswith("xl/") for name in names):
            return "xlsx"
    suffix = Path(filename or urlsplit(url).path).suffix.lower()
    return {
        ".pdf": "pdf",
        ".docx": "docx",
        ".xlsx": "xlsx",
        ".xlsm": "xlsx",
    }.get(suffix, "unknown")


def _pdf_text(content: bytes) -> str:
    chunks = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages[:MAX_PDF_PAGES]:
            chunks.append(page.extract_text() or "")
    return clean_text("\n".join(chunks))[:MAX_TEXT_CHARS]


def _docx_text(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    chunks = [p.text for p in doc.paragraphs if p.text]
    for table in doc.tables:
        for row in table.rows:
            cells = [clean_text(cell.text) for cell in row.cells]
            if any(cells):
                chunks.append(" | ".join(cells))
    return clean_text("\n".join(chunks))[:MAX_TEXT_CHARS]


def _xlsx_text(content: bytes) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    chunks = []
    for sheet in workbook.worksheets:
        chunks.append(f"[工作表 {sheet.title}]")
        for row in sheet.iter_rows(values_only=True):
            values = [clean_text(str(value)) if value is not None else "" for value in row]
            if any(values):
                chunks.append(" | ".join(values))
    workbook.close()
    return clean_text("\n".join(chunks))[:MAX_TEXT_CHARS]


def extract_attachment(
    fetcher: Fetcher, url: str, name: str = "", referer: str | None = None,
) -> dict:
    """下载并提取单个附件，返回可进入证据抽取的文本。"""
    suffix = Path(name or urlsplit(url).path).suffix.lower()
    if suffix in UNSUPPORTED_SUFFIXES:
        return {
            "name": name[:100], "url": url, "kind": suffix.lstrip("."),
            "text": "", "error": "暂不支持该旧版/压缩附件格式",
        }
    content, filename = fetcher.fetch_bytes(url, referer=referer)
    if content is None:
        return {
            "name": name[:100], "url": url, "kind": "unknown",
            "text": "", "error": "下载失败",
        }
    kind = _kind(url, filename or name, content)
    try:
        if kind == "pdf":
            text = _pdf_text(content)
            if not text:
                raise ValueError("PDF 没有可复制文本层")
        elif kind == "docx":
            text = _docx_text(content)
        elif kind == "xlsx":
            text = _xlsx_text(content)
        else:
            raise ValueError("暂不支持该附件类型")
    except Exception as exc:  # noqa: BLE001
        return {
            "name": name[:100], "url": url, "kind": kind,
            "text": "", "error": f"{type(exc).__name__}: {exc}"[:160],
        }
    return {
        "name": name[:100], "url": url, "kind": kind,
        "text": text, "error": "",
    }


def extract_attachments(
    fetcher: Fetcher, attachments: list[dict], referer: str,
    limit: int = MAX_ATTACHMENTS,
) -> list[dict]:
    def priority(item: dict) -> tuple[int, int]:
        label = f"{item.get('name', '')} {item.get('url', '')}".lower()
        relevant = sum(1 for term in PRIORITY_TERMS if term in label)
        suffix = Path(item.get("name") or urlsplit(item.get("url", "")).path).suffix.lower()
        unsupported = suffix in UNSUPPORTED_SUFFIXES
        return (int(unsupported), -relevant)

    out = []
    seen = set()
    for item in sorted(attachments, key=priority):
        url = item.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(
            extract_attachment(
                fetcher, url, name=item.get("name") or item.get("title") or "",
                referer=referer,
            )
        )
        if len(out) >= limit:
            break
    return out
