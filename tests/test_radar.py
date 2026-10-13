"""阶段一自测：抽取、归一化、目录匹配、评估分层。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radar.catalog import Catalog  # noqa: E402
from radar.config import load_config  # noqa: E402
from radar.evaluate import evaluate  # noqa: E402
from radar.extract import extract_fields, guess_competition_name, summarize_dates  # noqa: E402
from radar.store import Change, Store  # noqa: E402
from radar.textutil import canonical_url, find_dates, normalize_name  # noqa: E402


SAMPLE = """
关于组织参加2026年全国大学生软件测试大赛的通知
各学院：
本次大赛由教育部高等学校计算机类专业教学指导委员会主办，云南大学软件学院承办。
一、参赛对象
全日制在校本科生均可报名参加，每队不超过3人，可跨学院组队。
二、报名安排
大赛报名通道于2026年9月20日8:00开启，报名截止时间为2026年10月30日24:00。
参赛学生须登录大赛平台（www.mooctest.net）完成注册。
三、竞赛时间
省赛时间：2026年11月15日，决赛拟于2026年12月20日举行。
四、费用
本次大赛不收取报名费。
"""


class TestTextUtil(unittest.TestCase):
    def test_canonical_url(self):
        self.assertEqual(
            canonical_url("http://www.jwc.ynu.edu.cn/info/1009/4389.htm"),
            canonical_url("https://jwc.ynu.edu.cn/info/1009/4389.htm/"),
        )
        self.assertNotEqual(
            canonical_url("https://jwc.ynu.edu.cn/info/1009/4389.htm"),
            canonical_url("https://jwc.ynu.edu.cn/info/1009/4390.htm"),
        )

    def test_find_dates(self):
        dates = [d["value"] for d in find_dates("报名截止时间为2026年10月30日24:00")]
        self.assertIn("2026-10-30", dates)

    def test_normalize_name(self):
        self.assertEqual(normalize_name("2026年全国大学生软件测试大赛"),
                         normalize_name("全国大学生软件测试大赛"))


class TestExtract(unittest.TestCase):
    def test_guess_name(self):
        self.assertEqual(
            guess_competition_name("关于组织参加2026年全国大学生软件测试大赛的通知"),
            "全国大学生软件测试大赛",
        )

    def test_fields(self):
        out = extract_fields("通知标题", SAMPLE, "https://example.edu.cn/a.htm",
                             published_at="2026-09-01")
        summary = summarize_dates(out)
        self.assertEqual(summary["registration_last"], "2026-10-30")
        reg_evidence = " ".join(e["evidence"] for e in out["registration"])
        self.assertIn("2026年10月30日", reg_evidence)
        self.assertTrue(any("免费" in e["value"] or "不收取" in e["value"] for e in out["fee"]))
        self.assertTrue(any("3人" in e["value"] for e in out["team"]))
        self.assertTrue(any("本科生" in e["value"] for e in out["eligibility"]))
        self.assertTrue(any("主办" in e["evidence"] for e in out["organizer"]))

    def test_registration_requires_real_date(self):
        """只有"报名方式：邮箱"这类文字时，不能凭空产生时间。"""
        out = extract_fields("x", "报名方式：将报名表发送至 test@example.com", "u",
                             published_at="2026-03-01")
        self.assertEqual(summarize_dates(out)["registration_last"], None)


class TestCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / "data" / "catalog_ynu_2025.json"
        if not cls.path.exists():
            raise unittest.SkipTest("尚未生成目录数据")
        cls.catalog = Catalog.load(cls.path)

    def test_catalog_integrity(self):
        self.assertEqual(len(self.catalog.entries), 126)
        self.assertEqual(
            self.catalog.categories, {"一类": 2, "二类": 16, "三类": 71, "四类": 37}
        )

    def test_match_exact_and_miss(self):
        entry, score, method = self.catalog.match("全国大学生软件测试大赛")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.no, 100)
        self.assertEqual(entry.category, "四类")
        self.assertGreater(score, 0.8)

        entry2, score2, _ = self.catalog.match("2026年某不存在的全球编程大奖赛")
        self.assertIsNone(entry2)
        self.assertEqual(score2, 0.0)

    def test_match_inside_notice_title(self):
        entry, _, _ = self.catalog.match(
            guess_competition_name("关于组织参加2026年中国大学生计算机设计大赛的通知")
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry.name, "中国大学生计算机设计大赛")


class TestEvaluate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config(ROOT)
        cls.meta = {"title": "云南大学认定本科生学科竞赛目录（2025版）",
                    "source_url": "https://jwc.ynu.edu.cn/info/1009/3988.htm",
                    "version": "2025版"}

    def _record(self, **kw):
        base = {
            "key": "k",
            "name": "全国大学生软件测试大赛",
            "notices": [{"title": "关于组织参加2026年全国大学生软件测试大赛的通知",
                         "url": "https://jwc.ynu.edu.cn/info/1009/4389.htm",
                         "body_excerpt": "由教育部主办，云南大学软件学院承办"}],
            "registration_last": None,
            "registration_evidence": [],
            "student_reviews": [],
        }
        base.update(kw)
        return base

    def test_dimensions_are_separate(self):
        rec = evaluate(self._record(catalog_category="四类", catalog_no=100), self.cfg, self.meta)
        keys = {d["key"] for d in rec["dimensions"]}
        self.assertEqual(
            keys, {"catalog", "acceptance", "organizer", "cs_fit", "timeliness", "history"}
        )
        acceptance = next(d for d in rec["dimensions"] if d["key"] == "acceptance")
        # 没有综测规则文件时，综测维度必须是"未核实"，不能因为进了目录就默认有加分
        self.assertEqual(acceptance["status"], "unverified")
        self.assertEqual(acceptance["score"], 0)

    def test_acceptance_upgrades_only_to_school_level(self):
        szcp = {
            "meta": {"document_no": "云大学〔2020〕2号",
                     "sources": [{"url": "http://www.xsjzwh.ynu.edu.cn/info/1019/2264.htm",
                                  "role": "校级办法引用出处", "quote": "…云大学〔2020〕2号"}]},
            "competition_bonus": {
                "verified_conclusion": "学科竞赛获奖落在 G22 模块，上限 5 分。",
                "open_question": "具体分值由学院细则规定。",
            },
        }
        rec = evaluate(self._record(catalog_category="四类", catalog_no=100), self.cfg,
                       self.meta, szcp=szcp)
        acceptance = next(d for d in rec["dimensions"] if d["key"] == "acceptance")
        self.assertEqual(acceptance["status"], "partially-verified")
        self.assertEqual(acceptance["score"], 5)  # 只到校级，不冒充赛事级
        self.assertIn("云大学〔2020〕2号", acceptance["detail"])

    def test_history_dimension(self):
        rec = evaluate(self._record(catalog_category="三类", catalog_no=69), self.cfg,
                       self.meta, history_years=3)
        history = next(d for d in rec["dimensions"] if d["key"] == "history")
        self.assertEqual(history["score"], 4)
        self.assertIn("3 个年度", history["detail"])

    def test_weak_fit_never_focus(self):
        rec = evaluate(
            self._record(name="全国大学生英语演讲比赛",
                         notices=[{"title": "关于组织参加英语演讲比赛的通知",
                                   "url": "https://jwc.ynu.edu.cn/info/1009/1.htm",
                                   "body_excerpt": "由教育部主办"}]),
            self.cfg, self.meta,
        )
        self.assertEqual(rec["tier"], "低优先级/证据不足")

    def test_actionable_core_competition_is_focus(self):
        """计算机核心赛道 + 30 天内截止 + 分数达标 -> 重点关注。"""
        from datetime import date, timedelta

        soon = (date.today() + timedelta(days=10)).isoformat()
        rec = evaluate(
            self._record(catalog_category="四类", catalog_no=100, registration_last=soon),
            self.cfg, self.meta, history_years=2, szcp={
                "meta": {"document_no": "云大学〔2020〕2号", "sources": []},
                "competition_bonus": {"verified_conclusion": "x", "open_question": "y"},
            },
        )
        self.assertEqual(rec["deadline_status"], "30天内截止")
        self.assertEqual(rec["tier"], "重点关注")

    def test_no_date_keeps_out_of_focus(self):
        """三类赛事但没有拿到任何报名时间时，不应冒充"重点关注"。"""
        rec = evaluate(
            self._record(catalog_category="三类", catalog_no=69),
            self.cfg, self.meta, history_years=1,
        )
        self.assertEqual(rec["tier"], "潜在机会")


    def test_unlisted_competition_is_flagged(self):
        rec = evaluate(self._record(catalog_category=None), self.cfg, self.meta)
        catalog_dim = next(d for d in rec["dimensions"] if d["key"] == "catalog")
        self.assertEqual(catalog_dim["status"], "negative")
        self.assertTrue(any("认定目录" in r for r in rec["risks"]))

    def test_focus_requires_evidence(self):
        rec = evaluate(
            self._record(catalog_category="二类", catalog_no=8,
                         registration_last="2026-11-01"),
            self.cfg, self.meta,
        )
        self.assertEqual(rec["tier"], "重点关注")

    def test_achievement_only_cannot_be_focus(self):
        rec = evaluate(
            self._record(catalog_category="二类", catalog_no=8, notices=[],
                         registration_last="2026-11-01"),
            self.cfg, self.meta,
        )
        self.assertNotEqual(rec["tier"], "重点关注")


class TestStore(unittest.TestCase):
    """数据库层：历史留痕、变化检测、推送去重。"""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "test.db")
        self.store.start_run()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _rec(self, **kw):
        base = {
            "key": "catalog:100",
            "name": "全国大学生软件测试大赛",
            "catalog_no": 100,
            "catalog_category": "四类",
            "tier": "重点关注",
            "registration_last": "2026-10-30",
        }
        base.update(kw)
        return base

    def test_first_seen_is_preserved_across_runs(self):
        rec = self._rec()
        self.store.upsert_competition(rec, first_seen="2026-01-01T00:00:00+08:00",
                                      last_verified="2026-01-01T00:00:00+08:00")
        row = self.store.get_competition("catalog:100")
        self.assertEqual(row["first_seen"], "2026-01-01T00:00:00+08:00")
        # 第二轮只更新核验时间，首次发现时间不能被覆盖
        self.store.upsert_competition(rec, first_seen=row["first_seen"],
                                      last_verified="2026-02-02T00:00:00+08:00")
        self.assertEqual(self.store.get_competition("catalog:100")["first_seen"],
                         "2026-01-01T00:00:00+08:00")

    def test_notice_dedupe_by_canonical_url(self):
        n1 = {"url": "http://www.jwc.ynu.edu.cn/info/1009/4389.htm", "title": "t1"}
        n2 = {"url": "https://jwc.ynu.edu.cn/info/1009/4389.htm/", "title": "t2"}
        id1 = self.store.upsert_notice(n1)
        id2 = self.store.upsert_notice(n2)
        self.assertEqual(id1, id2)
        self.assertEqual(self.store.summary()["notices"], 1)

    def test_change_detection_and_history(self):
        comp_id = self.store.upsert_competition(self._rec(), first_seen="2026-01-01",
                                                last_verified="2026-01-01")
        self.store.link(comp_id, self.store.upsert_notice(
            {"url": "https://jwc.ynu.edu.cn/info/1009/1.htm", "title": "2025 通知",
             "published_at": "2025-09-01"}))
        self.assertEqual(self.store.notice_years(comp_id), {"2025"})

        self.store.add_change(Change(
            competition="全国大学生软件测试大赛", change_type="日期变化",
            field="registration_last", old_value="2026-10-20", new_value="2026-10-30",
            detail="报名截止：2026-10-20 → 2026-10-30", competition_id=comp_id,
        ))
        changes = self.store.recent_changes()
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["change_type"], "日期变化")

    def test_push_is_queued_once(self):
        comp_id = self.store.upsert_competition(self._rec(), first_seen="2026-01-01",
                                                last_verified="2026-01-01")
        key = "catalog:100|临近截止|2026-10-30"
        self.assertTrue(self.store.queue_push(key, comp_id, "软件测试大赛", "临近截止",
                                              "临近截止：软件测试大赛", "body"))
        self.assertFalse(self.store.queue_push(key, comp_id, "软件测试大赛", "临近截止",
                                               "临近截止：软件测试大赛", "body"))
        self.assertEqual(len(self.store.pending_pushes()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
