"""核心逻辑测试：列表解析、分类、去重、报告。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw.classify import is_relevant, match_tracks, signal_type  # noqa: E402
from cw.config import load  # noqa: E402
from cw.llm import action_is_stale  # noqa: E402
from cw.parse import parse_list  # noqa: E402
from cw.report import render  # noqa: E402
from cw.store import Store  # noqa: E402

TODAY = date.today()
RECENT = (TODAY - timedelta(days=10)).isoformat()
OLD = (TODAY - timedelta(days=500)).isoformat()


class TestParse(unittest.TestCase):
    def test_filters_old_nav_and_company_links(self):
        html = f"""
        <ul>
          <li><a href="/a1.html">中国电科2027届校园招聘正式启动</a><span>{RECENT}</span></li>
          <li><a href="/a2.html">关于开展2023年社会招聘的公告</a><span>{OLD}</span></li>
          <li><a href="/">南京莱斯信息技术股份有限公司</a></li>
          <li><a href="/a3.html">更多</a></li>
        </ul>
        """
        items = parse_list(html, "https://example.com/", lookback_days=365)
        titles = [i["title"] for i in items]
        self.assertIn("中国电科2027届校园招聘正式启动", titles)
        self.assertNotIn("关于开展2023年社会招聘的公告", titles)  # 太旧
        self.assertNotIn("南京莱斯信息技术股份有限公司", titles)  # 成员企业
        self.assertNotIn("更多", titles)  # 导航

    def test_date_extracted(self):
        html = f'<li><a href="/a.html">南方电网电力AI大赛公告</a><span>{RECENT}</span></li>'
        items = parse_list(html, "https://example.com/")
        self.assertEqual(items[0]["published_at"], RECENT)


class TestClassify(unittest.TestCase):
    def test_signal_types(self):
        self.assertEqual(signal_type("中国电科2027届校园招聘正式启动"), "招聘")
        self.assertEqual(signal_type("某项目招标公告"), "项目")
        self.assertEqual(signal_type("集团召开年度工作会议"), "战略")
        self.assertEqual(signal_type("某研究院发布技术成果"), "技术")
        self.assertIsNone(signal_type("今天天气不错"))

    def test_noise_filtered(self):
        self.assertFalse(is_relevant("集团党组开展巡视工作"))
        self.assertFalse(is_relevant("学习贯彻重要讲话精神"))
        self.assertTrue(is_relevant("南方电网电力AI应用大赛公告"))

    def test_track_matching(self):
        cfg = load(ROOT)
        tracks = match_tracks("招聘嵌入式软件工程师，要求熟悉FPGA", cfg.tracks)
        self.assertIn("embedded", tracks)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    def test_dedupe_by_url(self):
        item = {
            "url": "https://example.com/a", "source_id": "s", "unit_id": "u",
            "level": 2, "title": "t", "signal_type": "招聘", "published_at": RECENT,
        }
        self.assertTrue(self.store.upsert(item))
        self.assertFalse(self.store.upsert(item))


class TestActionFreshness(unittest.TestCase):
    def test_expired_action_is_detected(self):
        self.assertTrue(action_is_stale("于2026年9月23日前报名", "2026-09-15"))
        self.assertTrue(action_is_stale("9月23日前报名", "2026-09-15"))

    def test_future_action_is_kept(self):
        self.assertFalse(action_is_stale("2027年3月1日前报名", "2026-09-15"))
        self.assertFalse(action_is_stale("查看报名条件", "2026-09-15"))


class TestReport(unittest.TestCase):
    def test_contains_levels_links_and_is_compact(self):
        cfg = load(ROOT)
        items = [
            {
                "url": "https://example.com/a", "title": "中国电科2027届校园招聘正式启动",
                "level": 1, "unit_path": "中国电科", "signal_type": "招聘",
                "source_name": "中国电科·招聘及公告", "published_at": RECENT,
                "tracks": [], "tags": [], "is_new": True,
                "triage": {"include": True, "reason": "校园招聘"},
            },
            {
                "url": "https://example.com/b", "title": "54所获批国家自然科学基金项目",
                "level": 2, "unit_path": "中国电科 > 54所", "signal_type": "项目",
                "source_name": "54所·新闻动态", "published_at": RECENT,
                "tracks": [], "tags": [], "is_new": True,
                "triage": {"include": True, "reason": "技术项目"},
            },
        ]
        text = render(items, cfg, {
            "sources_ok": 2, "sources_total": 2, "raw_items": 2,
            "new_items": 2, "triaged": 2,
        })
        self.assertIn("L1 集团总部", text)
        self.assertIn("L2 院所/子公司", text)
        self.assertIn("https://example.com/a", text)
        self.assertLess(len(text), 4200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
