"""Extract text from the YNU competition catalog PDFs."""

import sys
from pathlib import Path

import fitz

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

for name in ["att_2025_b", "att_2022_a"]:
    p = RAW / (name + ".pdf")
    if not p.exists():
        print("missing", p)
        continue
    doc = fitz.open(p)
    print("#" * 70)
    print(f"{name}.pdf  pages={doc.page_count}")
    txt_path = RAW / (name + ".txt")
    chunks = []
    for i, page in enumerate(doc):
        t = page.get_text("text")
        chunks.append(f"\n----- page {i + 1} -----\n{t}")
    all_text = "".join(chunks)
    txt_path.write_text(all_text, encoding="utf-8")
    print(all_text[:3000])
    print(f"\n[saved full text -> {txt_path}, chars={len(all_text)}]")
    doc.close()
    print()
