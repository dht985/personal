"""针对外部评审意见修复项的回归测试。"""

from __future__ import annotations

import json
import sys
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radar.catalog import Catalog  # noqa: E402
from radar.config import load_config  # noqa: E402
from radar.evaluate import classify_organizer, evaluate  # noqa: E402


class TestCatalogConflict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / "data" / "catalog_ynu_2026.json"
        if not path.exists():
            raise unittest.SkipTest("目录数据不存在")
        cls.catalog = Catalog.load(path)

    def test_american_mcm_is_not_cumcm(self):
        """美赛（MCM）不能因为名字里都有"数学建模竞赛"就被当成国赛（CUMCM）。"""
        entry, _score, _method = self.catalog.match("美国大学生数学建模竞赛")
        self.assertIsNone(entry)

    def test_asia_pacific_mcm_is_not_cumcm(self):
        entry, _score, _method = self.catalog.match("亚太地区大学生数学建模竞赛")
        self.assertIsNone(entry)

    def test_cumcm_still_matches(self):
        entry, _score, _method = self.catalog.match("全国大学生数学建模竞赛")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.name, "全国大学生数学建模竞赛")

    def test_international_qualifier_allowed_when_catalog_has_it(self):
        # 目录条目本身带"国际"，不应被冲突词误伤
        entry, _score, _method = self.catalog.match("ACM-ICPC国际大学生程序设计竞赛")
        self.assertIsNotNone(entry)


class TestOrganizerAnchoring(unittest.TestCase):
    def test_provincial_selection_mentioning_national_final(self):
        level, _ = classify_organizer(
            "云南省教育厅主办，云南省大学生竞赛组委会承办。选拔优秀队伍参加全国总决赛。"
        )
        self.assertEqual(level, "省级")

    def test_explicit_organizer_field_wins(self):
        level, _ = classify_organizer(
            "主办单位：云南省教育厅。承办单位：云南大学。优秀队伍参加全国总决赛。"
        )
        self.assertEqual(level, "省级")

    def test_national_organizer(self):
        level, _ = classify_organizer("主办单位：教育部高等学校计算机类专业教学指导委员会。")
        self.assertEqual(level, "国家级")

    def test_no_organizer_is_unknown(self):
        level, _ = classify_organizer("现将有关事项通知如下，请各学院组织学生参加全国总决赛。")
        self.assertEqual(level, "未知")


class TestDynamicCatalogTitle(unittest.TestCase):
    def test_unlisted_detail_uses_loaded_catalog_title(self):
        cfg = load_config(ROOT)
        meta = {"title": "测试目录（2099版）", "source_url": "https://example.com/catalog"}
        record = {
            "key": "name:test", "name": "某个杯赛", "notices": [], "sources": [],
            "official_links": [], "student_reviews": [], "registration_evidence": [],
        }
        rec = evaluate(record, cfg, meta)
        catalog_dim = next(d for d in rec["dimensions"] if d["key"] == "catalog")
        self.assertIn("测试目录（2099版）", catalog_dim["detail"])
        self.assertIn("测试目录（2099版）", " ".join(rec["risks"]))
        self.assertNotIn("2025", catalog_dim["detail"])


class TestConfigHygiene(unittest.TestCase):
    def test_no_duplicate_discovery_queries(self):
        data = tomllib.loads((ROOT / "config" / "keywords.toml").read_text(encoding="utf-8"))
        queries = [q["q"] for q in data.get("discovery", {}).get("query", [])]
        duplicates = {q for q in queries if queries.count(q) > 1}
        self.assertEqual(duplicates, set(), f"重复检索式浪费 API 额度：{duplicates}")

    def test_python_version_declared(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Python 3.11", text)

    def test_scoring_threshold_matches_readme(self):
        scoring = tomllib.loads((ROOT / "config" / "scoring.toml").read_text(encoding="utf-8"))
        threshold = scoring["tier_rules"]["focus_min_score"]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"总分 ≥ {threshold}", readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
