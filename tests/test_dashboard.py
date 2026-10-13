"""仪表盘自测：数据内嵌是否完整、是否会被内容里的 </script> 破坏、中文是否原样保留。"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radar.dashboard import build_payload, render_dashboard  # noqa: E402


def _record(**kw):
    base = {
        "key": "catalog:100",
        "name": "全国大学生软件测试大赛",
        "tier": "重点关注",
        "score_total": 55,
        "catalog_category": "四类",
        "catalog_no": 100,
        "cs_fit": "核心",
        "deadline_status": "30天内截止",
        "deadline_detail": "报名截止 2026-10-30，还剩 17 天",
        "registration_last": "2026-10-30",
        "tier_reason": "计算机核心赛道且 30 天内截止",
        "risks": ["未找到足够可靠的公开学生评价"],
        "next_actions": ["核对官方通知原文中的报名入口与截止时间"],
        "dimensions": [
            {"key": "catalog", "label": "云南大学认定目录", "score": 12,
             "status": "verified", "detail": "四类", "evidence": []},
            {"key": "acceptance", "label": "综合测评赋分", "score": 5,
             "status": "partially-verified", "detail": "校级已核实",
             "evidence": [{"url": "http://www.xsjzwh.ynu.edu.cn/info/1019/2264.htm",
                           "quote": "云大学〔2020〕2号"}]},
        ],
        "notices": [{"title": "关于组织参加2026年全国大学生软件测试大赛的通知",
                     "url": "https://jwc.ynu.edu.cn/info/1009/4389.htm",
                     "source_name": "云南大学本科生院（教务处）", "authority": "official",
                     "published_at": "2026-09-18", "body_excerpt": "报名截止时间"}],
        "registration_evidence": [{"evidence": "报名截止时间为2026年10月30日24:00"}],
        "first_seen": "2026-10-13T18:00:00+08:00",
        "last_verified": "2026-10-13T18:40:00+08:00",
        "authority": "official",
        "history_years": ["2025", "2026"],
    }
    base.update(kw)
    return base


META = {"title": "云南大学认定本科生学科竞赛目录（2025版）", "count": 126, "version": "2025版"}


class TestDashboard(unittest.TestCase):
    def test_payload_counts_and_chips(self):
        payload = build_payload(
            [_record(), _record(key="catalog:69", name="蓝桥杯全国软件和信息技术专业人才大赛",
                                tier="潜在机会", score_total=57)],
            [{"kept": True, "title": "外校通知", "real_url": "https://x.edu.cn/a.htm",
              "catalog_category": "三类"},
             {"kept": False, "title": "被过滤掉的结果"}],
            {"records": 2, "official_notices": 222, "discovery_kept": 126},
            META, [], [],
        )
        self.assertEqual(payload["tier_counts"]["重点关注"], 1)
        self.assertEqual(payload["tier_counts"]["潜在机会"], 1)
        # 未通过过滤的发现结果不应出现在页面上
        self.assertEqual(len(payload["discovery"]), 1)
        self.assertEqual(payload["discovery_total"], 1)
        chip_names = [c[0] for c in payload["chips"]]
        self.assertIn("重点关注", chip_names)

    def test_primary_notice_prefers_school_official(self):
        rec = _record(notices=[
            {"title": "外校转发", "url": "https://other.edu.cn/a.htm",
             "source_name": "某高校", "authority": "aggregator"},
            {"title": "校内通知", "url": "https://jwc.ynu.edu.cn/info/1009/4389.htm",
             "source_name": "本科生院", "authority": "official"},
        ])
        payload = build_payload([rec], [], {}, META, [], [])
        self.assertIn("jwc.ynu.edu.cn", payload["records"][0]["primary_url"])

    def test_render_replaces_placeholder(self):
        payload = build_payload([_record()], [], {}, META, [], [])
        html = render_dashboard(payload)
        self.assertNotIn("/*__DATA__*/", html)
        self.assertIn("全国大学生软件测试大赛", html)
        self.assertIn("<!doctype html>", html.lower())

    def test_json_payload_is_parseable_from_html(self):
        payload = build_payload([_record()], [], {}, META, [], [])
        html = render_dashboard(payload)
        m = re.search(r"const DATA = (\{.*?\});\n", html, re.S)
        self.assertIsNotNone(m, "没有在 HTML 里找到内嵌数据")
        parsed = json.loads(m.group(1).replace("<\\/", "</"))
        self.assertEqual(len(parsed["records"]), 1)
        self.assertEqual(parsed["records"][0]["tier"], "重点关注")
        # 分维度证据要带进页面，否则弹窗里看不到原文
        acceptance = next(d for d in parsed["records"][0]["dimensions"]
                          if d["key"] == "acceptance")
        self.assertIn("云大学〔2020〕2号", acceptance["evidence"][0]["quote"])

    def test_script_tag_in_content_cannot_break_page(self):
        nasty = _record(name="奇怪的赛事</script><script>alert(1)</script>")
        payload = build_payload([nasty], [], {}, META, [], [])
        html = render_dashboard(payload)
        # 内嵌数据里不能出现真正的结束标签
        data_region = html.split("const DATA = ", 1)[1].split(";\n", 1)[0]
        self.assertNotIn("</script>", data_region)


if __name__ == "__main__":
    unittest.main(verbosity=2)
