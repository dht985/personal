"""Print selected parts of the reconnaissance report with readable UTF-8 output."""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "data" / "recon_report.json").read_text(encoding="utf-8"))

for r in data:
    print(f"=== {r['name']}  [{r.get('status')}]  {r.get('final_url', r['url'])}")
    if not r.get("kw_links"):
        print("    (no keyword links)")
    for kw in r.get("kw_links", []):
        print(f"    - {kw['text']}  ->  {kw['href']}")
    print()
