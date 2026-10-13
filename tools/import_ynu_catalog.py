"""把《云南大学认定本科生学科竞赛目录》PDF 转成结构化 JSON。

用法:
    python tools/import_ynu_catalog.py --pdf data/raw/att_2025_b.pdf \
        --source-url "https://jwc.ynu.edu.cn/info/1009/3988.htm" \
        --version "2025版" --out data/catalog_ynu_2025.json

解析基于 PDF 的列坐标（序号/竞赛名称/承办单位/竞赛负责人/类别），
因此换一版目录文件时只要版式一致就能直接复用。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pdfplumber

CATEGORIES = ("一类", "二类", "三类", "四类")
HEADER = ["序号", "竞赛名称", "承办单位", "竞赛负责人", "类别"]


def _cell(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").replace("\n", ""))


def parse_pdf(pdf_path: Path) -> list[dict]:
    """按表格线提取，单元格内的换行会自动拼回。"""
    entries: list[dict] = []
    seen_no: set[int] = set()
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table or []:
                    if not row or len(row) < 5:
                        continue
                    no_raw = _cell(row[0])
                    if not re.fullmatch(r"\d{1,3}", no_raw):
                        continue  # 表头或页码
                    no = int(no_raw)
                    if no in seen_no:
                        continue
                    name = _cell(row[1])
                    category = _cell(row[4])
                    if not name or category not in CATEGORIES:
                        continue
                    seen_no.add(no)
                    entries.append(
                        {
                            "no": no,
                            "name": name,
                            "dept": _cell(row[2]),
                            "owner": _cell(row[3]),
                            "category": category,
                        }
                    )
    entries.sort(key=lambda e: e["no"])
    return entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-url", default="")
    ap.add_argument("--attachment-url", default="")
    ap.add_argument("--version", default="")
    args = ap.parse_args()

    pdf_path = Path(args.pdf)
    raw = pdf_path.read_bytes()
    entries = parse_pdf(pdf_path)

    dist: dict[str, int] = {}
    for e in entries:
        dist[e["category"]] = dist.get(e["category"], 0) + 1

    payload = {
        "meta": {
            "title": f"云南大学认定本科生学科竞赛目录（{args.version}）" if args.version else "云南大学认定本科生学科竞赛目录",
            "version": args.version,
            "source_url": args.source_url,
            "attachment_url": args.attachment_url,
            "local_file": str(pdf_path.as_posix()),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "imported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "count": len(entries),
            "category_distribution": dist,
            "note": "本文件由官方附件自动解析生成，内容未经人工改写。",
        },
        "entries": entries,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"解析条目数: {len(entries)}")
    print(f"类别分布: {dist}")
    bad = [e for e in entries if not e["name"] or e["category"] not in CATEGORIES]
    if bad:
        print(f"异常条目 {len(bad)} 条，示例: {bad[:3]}")
    print(f"输出 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
