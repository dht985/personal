"""把 PDF 全文抽成 txt，便于人工核对与后续解析。用法：

    python tools/extract_pdf_text.py <pdf路径> [输出txt路径]
"""

import sys
from pathlib import Path

import pdfplumber

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    pdf_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else pdf_path.with_suffix(".txt")
    chunks: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            chunks.append(f"\n===== page {i + 1} =====\n" + (page.extract_text() or ""))
    text = "".join(chunks)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"{pdf_path.name}: {len(text)} 字符 -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
