"""读取 docx 正文与表格，按文档顺序输出。"""

import sys
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

path = Path(sys.argv[1])
doc = Document(str(path))


def iter_blocks(document):
    body = document.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


for block in iter_blocks(doc):
    if isinstance(block, Paragraph):
        text = block.text.strip()
        if text:
            style = block.style.name if block.style else ""
            prefix = f"[{style}] " if style and style != "Normal" else ""
            print(prefix + text)
    else:
        print("\n--- 表格 ---")
        for row in block.rows:
            cells = [" ".join(c.text.split()) for c in row.cells]
            print(" | ".join(cells))
        print("--- 表格结束 ---\n")
