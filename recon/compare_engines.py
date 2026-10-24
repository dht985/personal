"""对比搜狗与 360 在同一批发现查询上的覆盖差异。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from radar.config import load_config  # noqa: E402
from radar.net import Fetcher  # noqa: E402
from radar.sources import resolve_redirect, resolve_sogou, search_360, search_sogou  # noqa: E402
from radar.ynu_profile import is_ynu  # noqa: E402

QUERIES = [
    "全国大学生 计算机 竞赛 2026 报名通知",
    "云南大学 学科竞赛 通知 2026",
    "中国高校计算机大赛 2026",
    "大学生 人工智能 大赛 2026 报名通知",
]


def run(fn, fetcher, q, resolver):
    out = []
    for item in fn(fetcher, q, pages=1)[:8]:
        url = item.get("url") or ""
        if "so.com/link" in url:
            url = resolve_redirect(fetcher, url)
        elif "sogou.com/link" in url:
            url = resolver(fetcher, url)
        out.append({"title": item.get("title", ""), "url": url})
    return out


def main() -> int:
    cfg = load_config(ROOT)
    fetcher = Fetcher(cfg)
    total_s = total_3 = 0
    ynu_s = ynu_3 = 0
    for q in QUERIES:
        s = run(search_sogou, fetcher, q, resolve_sogou)
        t = run(search_360, fetcher, q, resolve_redirect)
        total_s += len(s)
        total_3 += len(t)
        ys = sum(1 for x in s if is_ynu(x["url"]))
        yt = sum(1 for x in t if is_ynu(x["url"]))
        ynu_s += ys
        ynu_3 += yt
        print(f"\nQ: {q}")
        print(f"  搜狗 {len(s)} 条（云大 {ys}） | 360 {len(t)} 条（云大 {yt}）")
        s_titles = {x["title"][:24] for x in s}
        t_titles = {x["title"][:24] for x in t}
        print(f"  标题重合 {len(s_titles & t_titles)} 条；搜狗独有 {len(s_titles - t_titles)} 条")
        for x in s[:3]:
            flag = "YNU" if is_ynu(x["url"]) else "   "
            print(f"    [S] {flag} {x['title'][:56]}")
        for x in t[:2]:
            flag = "YNU" if is_ynu(x["url"]) else "   "
            print(f"    [3] {flag} {x['title'][:56]}")
    print(f"\n合计：搜狗 {total_s} 条（云大 {ynu_s}） | 360 {total_3} 条（云大 {ynu_3}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
