"""Download the notice attachments and identify what they contain."""

import sys
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "http://www.jwc.ynu.edu.cn/info/1009/3988.htm",
}

ATT = [
    ("http://www.jwc.ynu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1429239689&wbfileid=15383682", "att_2025_a"),
    ("http://www.jwc.ynu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1429239689&wbfileid=15383683", "att_2025_b"),
    ("http://www.jwc.ynu.edu.cn/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=1429239689&wbfileid=7725565", "att_2022_a"),
]

for url, name in ATT:
    try:
        r = requests.get(url, headers=HEADERS, timeout=40, allow_redirects=True)
        cd = r.headers.get("Content-Disposition", "")
        print(f"[{r.status_code}] {name}  type={r.headers.get('Content-Type')}  bytes={len(r.content)}")
        print("   disposition:", cd[:160])
        suffix = ".bin"
        low = cd.lower()
        for ext in (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".zip"):
            if ext in low:
                suffix = ext
                break
        p = RAW / (name + suffix)
        p.write_bytes(r.content)
        print("   saved:", p)
    except Exception as exc:
        print(f"   ERR {name}: {exc}")
