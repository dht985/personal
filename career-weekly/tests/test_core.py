"""核心逻辑测试：列表解析、分类、去重、报告。"""

from __future__ import annotations

import sys
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cw.classify import is_relevant, match_tracks, signal_type  # noqa: E402
from cw.config import load, source_purpose  # noqa: E402
from cw.discover_sources import candidate_links  # noqa: E402
from cw.enrich import content_digest, extract_facts, parse_deadline  # noqa: E402
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
        self.assertEqual(signal_type("集团发布人工智能发展规划"), "政策")
        self.assertEqual(signal_type("数据安全管理办法正式施行"), "政策")
        self.assertEqual(
            signal_type("国家能源投资集团有限责任公司2027年度高校毕业生统招公告"),
            "招聘",
        )
        self.assertNotEqual(signal_type("从经验规划到智能决策的配网变革"), "政策")
        self.assertEqual(signal_type("某项目招标公告"), "采购")
        self.assertEqual(signal_type("某项目建设正式开工"), "项目")
        self.assertEqual(signal_type("集团完成战略投资"), "投资")
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

    def test_policy_source_keeps_policy_notice(self):
        self.assertTrue(is_relevant("集团发布发展规划", "policy"))
        self.assertFalse(is_relevant("集团发布发展规划", "news"))


class TestSourcePurpose(unittest.TestCase):
    def test_explicit_and_inferred_purpose(self):
        self.assertEqual(source_purpose({"purpose": "recruit"}), "recruit")
        self.assertEqual(source_purpose({"name": "某某·招聘公告"}), "recruit")
        self.assertEqual(source_purpose({"name": "某某·信息公开"}), "policy")
        self.assertEqual(source_purpose({"name": "某某·新闻中心"}), "news")

    def test_config_keeps_all_manual_sources_without_url(self):
        cfg = load(ROOT)
        manual_ids = {
            source["id"] for source in cfg.sources if source.get("kind") == "manual"
        }
        self.assertEqual(
            manual_ids,
            {"manual-211", "manual-sgcc", "manual-cnpc"},
        )


class TestDiscovery(unittest.TestCase):
    def test_candidate_links_are_scoped_and_ranked(self):
        raw = """
        <a href="/news/">集团新闻中心</a>
        <a href="/jobs/">人才招聘</a>
        <a href="https://other.example/jobs/">外部招聘</a>
        <a href="https://www.example.com/recruit/">校园招聘公告</a>
        """
        links = candidate_links(
            raw, "https://www.example.com/", "recruit",
            "https://www.example.com/",
        )
        self.assertEqual(len(links), 2)
        self.assertTrue(all("example.com" in item["url"] for item in links))
        self.assertTrue(any("校园招聘公告" in item["title"] for item in links))


class TestEnrich(unittest.TestCase):
    def test_extracts_only_source_facts(self):
        text = (
            "校园招聘对象为本科及以上学历。专业要求：计算机科学与技术、软件工程、"
            "人工智能。工作地点：昆明。报名截止时间：2026年11月20日。"
        )
        deadline = parse_deadline(text)
        self.assertEqual(deadline["date"], "2026-11-20")
        facts = extract_facts("2027届技术招聘", text, [], RECENT)
        self.assertIn("校园招聘", facts["employment_type"])
        self.assertIn("本科及以上", facts["education"])
        self.assertIn("人工智能", facts["technical_terms"])
        self.assertEqual(facts["locations"], ["昆明"])

    def test_deadline_prefers_end_of_range(self):
        deadline = parse_deadline("报名时间：2026年8月31日至9月23日。")
        self.assertEqual(deadline["date"], "2026-09-23")
        self.assertEqual(deadline["source"], "date_range")

    def test_deadline_uses_explicit_word(self):
        deadline = parse_deadline("本次报名至2026年9月21日17时截止。")
        self.assertEqual(deadline["date"], "2026-09-21")

    def test_deadline_ignores_age_cutoff(self):
        text = (
            "报名时间。自公告发布之日起至2026年9月23日。"
            "有关年龄和年限计算截至2026年8月31日。"
        )
        self.assertEqual(parse_deadline(text)["date"], "2026-09-23")

    def test_content_digest_changes_with_attachment(self):
        first = content_digest("公告", "正文", ["https://example.com/a.pdf"])
        second = content_digest("公告", "正文", ["https://example.com/b.pdf"])
        self.assertNotEqual(first, second)


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
        item["level"] = 3
        item["title"] = "更新后的标题"
        self.assertFalse(self.store.upsert(item))
        row = self.store.conn.execute("SELECT level, title FROM items").fetchone()
        self.assertEqual(row["level"], 3)
        self.assertEqual(row["title"], "更新后的标题")

    def test_discovery_attempt_is_persisted_and_upserted(self):
        url = "https://example.com/jobs/"
        self.store.record_discovery("u", "recruit", "招聘", url, "rejected", "短页面")
        self.assertIsNotNone(self.store.discovery_checked_at("u", "recruit", url))
        self.store.record_discovery("u", "recruit", "招聘", url, "accepted", "有效")
        row = self.store.conn.execute(
            "SELECT status, detail FROM discovery_attempts WHERE candidate_url = ?",
            (url,),
        ).fetchone()
        self.assertEqual(row["status"], "accepted")
        self.assertEqual(row["detail"], "有效")
        self.assertEqual(self.store.discovery_summary(), {"accepted": 1})

    def test_content_snapshot_detects_change(self):
        item = {
            "url": "https://example.com/job", "source_id": "s", "unit_id": "u",
            "level": 2, "title": "招聘公告", "signal_type": "招聘",
        }
        self.store.upsert(item)
        first = self.store.update_content(
            item["url"], "hash-a", "第一版正文", {"deadline": "2026-11-01"},
            extractor_version=2,
        )
        second = self.store.update_content(
            item["url"], "hash-b", "第二版正文", {"deadline": "2026-11-20"},
            extractor_version=2,
        )
        self.assertTrue(first["baseline"])
        self.assertFalse(first["changed"])
        self.assertTrue(second["changed"])
        count = self.store.conn.execute(
            "SELECT COUNT(*) AS n FROM item_snapshots"
        ).fetchone()["n"]
        self.assertEqual(count, 2)
        kind = self.store.conn.execute(
            "SELECT change_kind FROM item_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()["change_kind"]
        self.assertEqual(kind, "changed")

    def test_source_health_tracks_empty_then_recovers(self):
        self.store.record_source_health("s", "empty", 0)
        self.store.record_source_health("s", "empty", 0)
        row = self.store.conn.execute(
            "SELECT * FROM source_health WHERE source_id = 's'"
        ).fetchone()
        self.assertEqual(row["consecutive_empty"], 2)
        self.store.record_source_health("s", "ok", 3)
        row = self.store.conn.execute(
            "SELECT * FROM source_health WHERE source_id = 's'"
        ).fetchone()
        self.assertEqual(row["consecutive_empty"], 0)
        self.assertIsNotNone(row["last_success_at"])

    def test_old_database_migration_preserves_items(self):
        self.store.conn.close()
        old_path = Path(self.tmp.name) / "old.db"
        conn = sqlite3.connect(old_path)
        conn.execute(
            """CREATE TABLE items (
               id INTEGER PRIMARY KEY, url TEXT UNIQUE, source_id TEXT,
               unit_id TEXT, level INTEGER, title TEXT, signal_type TEXT,
               published_at TEXT, tracks TEXT, tags TEXT,
               first_seen TEXT, last_seen TEXT)"""
        )
        conn.execute(
            "INSERT INTO items VALUES (1, 'https://example.com/old', 's', 'u', 1, "
            "'旧公告', '招聘', NULL, '[]', '[]', '2026-01-01', '2026-01-01')"
        )
        conn.commit()
        conn.close()
        migrated = Store(old_path)
        columns = {
            row["name"] for row in migrated.conn.execute("PRAGMA table_info(items)")
        }
        self.assertIn("content_hash", columns)
        self.assertIn("extractor_version", columns)
        self.assertEqual(
            migrated.conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"], 1,
        )
        migrated.conn.close()


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
                "source_purpose": "recruit",
                "tracks": [], "tags": [], "is_new": True,
                "content_changed": True,
                "facts": {
                    "employment_type": ["校园招聘"],
                    "technical_terms": ["软件工程", "人工智能"],
                    "deadline": {"date": "2027-03-01"},
                },
                "triage": {"include": True, "reason": "校园招聘"},
            },
            {
                "url": "https://example.com/b", "title": "54所获批国家自然科学基金项目",
                "level": 2, "unit_path": "中国电科 > 54所", "signal_type": "项目",
                "source_name": "54所·新闻动态", "published_at": RECENT,
                "source_purpose": "news",
                "tracks": [], "tags": [], "is_new": True,
                "triage": {"include": True, "reason": "技术项目"},
            },
        ]
        text = render(items, cfg, {
            "sources_ok": 2, "sources_total": 2, "raw_items": 2,
            "new_items": 2, "triaged": 2,
            "source_purposes": {"recruit": 1, "policy": 2, "news": 3},
        })
        self.assertIn("L1 集团总部", text)
        self.assertIn("L2 院所/子公司", text)
        self.assertIn("https://example.com/a", text)
        self.assertIn("招聘源 1 个，政策源 2 个", text)
        self.assertIn("🔄", text)
        self.assertIn("技术词：软件工程、人工智能", text)
        self.assertLess(len(text), 4200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
