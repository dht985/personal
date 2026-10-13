"""综测规则自测：权重解析结果、加分计算、2025→2026 降级处理。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radar.szcp import SzcpRules  # noqa: E402

RULES_PATH = ROOT / "data" / "szcp_college.json"


class TestSzcpRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RULES_PATH.exists():
            raise unittest.SkipTest("尚未生成计科综测规则数据")
        cls.rules = SzcpRules.load(RULES_PATH)

    def test_rules_match_official_document(self):
        r = self.rules.rules
        self.assertEqual(r["cap"], 5.0)
        self.assertEqual(r["base_score"], {"国家级": 4.0, "省级": 2.0})
        self.assertEqual(r["category_weight"],
                         {"一类": 1.0, "二类": 0.9, "三类": 0.8, "四类": 0.7, "五类": 0.6})
        self.assertEqual(r["award_weight"],
                         {"一等及以上": 1.0, "二等": 0.6, "三等": 0.3, "其他": 0.1})
        self.assertEqual(r["rank_weight"],
                         {"第一": 1.0, "第二": 0.6, "第三": 0.3, "其他": 0.1})
        self.assertIn("团队排名分值权重", r["formula"])

    def test_provenance_recorded(self):
        meta = self.rules.meta
        self.assertIn("计科", meta["title"])
        self.assertEqual(meta["applicable_major"], "计算机科学与技术")
        self.assertTrue(meta["sha256"], "应当记录来源 PDF 的哈希，便于复核")

    def test_national_first_prize_by_category(self):
        # 一类：4 × 1.0 × 1.0 × 1.0 = 4 分
        self.assertAlmostEqual(self.rules.estimate("一类").capped, 4.0)
        # 二类：4 × 0.9 = 3.6
        self.assertAlmostEqual(self.rules.estimate("二类").capped, 3.6)
        # 三类：4 × 0.8 = 3.2
        self.assertAlmostEqual(self.rules.estimate("三类").capped, 3.2)
        # 四类：4 × 0.7 = 2.8
        self.assertAlmostEqual(self.rules.estimate("四类").capped, 2.8)

    def test_lower_award_and_rank_reduce_score(self):
        second = self.rules.estimate("二类", award="二等", rank="第二")
        # 4 × 0.9 × 0.6 × 0.6 = 1.296
        self.assertAlmostEqual(second.capped, 1.296, places=3)
        self.assertEqual(second.formula, "4 × 0.9 × 0.6 × 0.6 = 1.296 分")

    def test_cap_is_applied(self):
        # 构造一个超过上限的情形：国家级 4 分 × 最高权重也只到 4，不会超；
        # 这里验证上限字段本身生效（把上限临时调小）
        rules = SzcpRules(json.loads(json.dumps(self.rules.data)))
        rules.rules["cap"] = 2.0
        bonus = rules.estimate("一类")
        self.assertEqual(bonus.raw, 4.0)
        self.assertEqual(bonus.capped, 2.0)

    def test_provincial_base_score(self):
        self.assertAlmostEqual(self.rules.estimate("二类", level="省级").capped, 1.8)

    def test_downgrade_rule_for_dropped_competition(self):
        # 2026 目录里没有、2025 目录里是三类 -> 按四类算
        category, from_cat = self.rules.resolve_category(None, "三类")
        self.assertEqual(category, "四类")
        self.assertEqual(from_cat, "三类")
        bonus = self.rules.estimate(category, downgraded_from=from_cat)
        self.assertAlmostEqual(bonus.capped, 2.8)
        self.assertEqual(bonus.downgraded_from, "三类")

    def test_current_catalog_wins(self):
        category, from_cat = self.rules.resolve_category("二类", "三类")
        self.assertEqual(category, "二类")
        self.assertIsNone(from_cat)

    def test_no_category_returns_none(self):
        self.assertIsNone(self.rules.estimate(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
