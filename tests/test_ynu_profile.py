"""云大生态评估与"需导师/可自主"判定自测（不联网）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radar.catalog import CatalogEntry  # noqa: E402
from radar.requirement import assess_requirement  # noqa: E402
from radar.ynu_profile import Corpus, Evidence, _core, _mention_window, assess  # noqa: E402


def _record(name="全国大学生软件测试大赛", notices=None):
    return {
        "key": "k",
        "name": name,
        "notices": notices or [
            {
                "title": "关于组织参加2026年全国大学生软件测试大赛的通知",
                "url": "https://jwc.ynu.edu.cn/info/1009/4389.htm",
                "body_excerpt": "报名截止时间为2026年10月30日。参赛学生须登录大赛平台完成报名。",
            }
        ],
    }


def _corpus(text, label="信息学院竞赛动态", url="https://www.ise.ynu.edu.cn/directory/77/"):
    c = Corpus()
    c.add_page(label, url, text)
    return c


ENTRY = CatalogEntry(no=94, name="全国大学生软件测试大赛", dept="软件学院", owner="康洪炜", category="四类")


class TestMentionWindow(unittest.TestCase):
    def test_full_name_match_returns_local_window(self):
        text = "导航菜单" * 40 + "信息学院在全国大学生软件测试大赛中获佳绩" + "页脚" * 40
        window = _mention_window(text, "全国大学生软件测试大赛")
        self.assertIsNotNone(window)
        self.assertIn("获佳绩", window)
        self.assertLess(len(window), 200)

    def test_short_generic_word_does_not_match(self):
        # "设计大赛"太泛，不应该只因为它出现就认定是某具体赛事
        self.assertIsNone(_mention_window("学校举办设计大赛", "全国大学生计算机设计大赛"))

    def test_core_strips_generic_affixes(self):
        self.assertEqual(_core("全国大学生软件测试大赛"), "软件测试")


class TestVerdict(unittest.TestCase):
    def test_in_catalog_is_always_sufficient(self):
        profile = assess(_record(), _corpus(""), None, ENTRY, do_search=False)
        self.assertEqual(profile.verdict, "sufficient")
        self.assertTrue(profile.in_catalog)

    def test_no_evidence_outside_catalog_is_insufficient(self):
        record = _record("某个不知名杯赛", notices=[
            {"title": "赛事启动", "url": "https://example.com/a.htm",
             "body_excerpt": "某个不知名杯赛开始报名"},
        ])
        profile = assess(record, _corpus("今天天气不错"), None, None, do_search=False)
        self.assertEqual(profile.verdict, "insufficient")
        self.assertFalse(profile.included)

    def test_search_failure_is_inconclusive_not_insufficient(self):
        profile = assess(_record("某个不知名杯赛"), _corpus("今天天气不错"), None, None,
                         do_search=True, engine_ok=False)
        self.assertEqual(profile.verdict, "inconclusive")
        self.assertTrue(profile.included)

    def test_single_dimension_is_inconclusive(self):
        corpus = _corpus("信息学院收到某个不知名杯赛的参赛邀请函")
        profile = assess(_record("某个不知名杯赛"), corpus, None, None, do_search=False)
        self.assertEqual(profile.verdict, "inconclusive")
        self.assertTrue(profile.included)

    def test_two_dimensions_are_sufficient(self):
        corpus = _corpus("信息学院组织参加某个不知名杯赛，并在该赛事中获佳绩")
        profile = assess(_record("某个不知名杯赛"), corpus, None, None, do_search=False)
        self.assertEqual(profile.verdict, "sufficient")

    def test_own_ynu_notice_counts_as_awareness(self):
        record = _record("某个不知名杯赛")
        profile = assess(record, _corpus(""), None, None, do_search=False)
        awareness = profile.dimensions[0]
        self.assertEqual(awareness.status, "found")
        self.assertIn("校内通知", awareness.evidence[0].source)

    def test_other_school_news_does_not_count(self):
        corpus = _corpus("某外校在全国大学生软件测试大赛中获奖",
                         label="外校新闻", url="https://other.edu.cn/news/1.htm")
        # 语料本身是外部来源，需要靠 is_ynu 过滤；这里直接构造 Evidence 验证判定不依赖它
        record = _record("某个不知名杯赛", notices=[
            {"title": "外校新闻", "url": "https://other.edu.cn/news/1.htm",
             "body_excerpt": "某外校在某个不知名杯赛中获奖"},
        ])
        profile = assess(record, Corpus(), None, None, do_search=False)
        self.assertIsNotNone(corpus)  # 语料构建可用
        self.assertEqual(profile.verdict, "insufficient")

    def _non_ynu_record(self, name):
        return _record(name, notices=[
            {"title": "赛事启动", "url": "https://example.com/a.htm",
             "body_excerpt": f"{name}开始报名"},
        ])

    def test_partial_search_failure_is_inconclusive(self):
        """两条查询一条成功一条失败：不能因为"没搜到"就判不足。"""
        calls = []

        def fake_search(fetcher, query, pages=1, ttl_hours=None):
            calls.append(query)
            if len(calls) == 1:
                return [], "serpapi-baidu", True
            return [], "none", False

        from radar import ynu_profile

        with mock.patch.object(ynu_profile, "search_web", side_effect=fake_search):
            profile = assess(self._non_ynu_record("某个不知名杯赛"), Corpus(), None, None,
                             do_search=True)

        self.assertEqual(profile.verdict, "inconclusive")
        self.assertEqual(profile.queries_run, 1)
        self.assertTrue(any("检索未全部完成" in n for n in profile.notes))

    def test_all_queries_complete_without_evidence_is_insufficient(self):
        def fake_search(fetcher, query, pages=1, ttl_hours=None):
            return [], "serpapi-baidu", True

        from radar import ynu_profile

        with mock.patch.object(ynu_profile, "search_web", side_effect=fake_search):
            profile = assess(self._non_ynu_record("某个不知名杯赛"), Corpus(), None, None,
                             do_search=True)

        self.assertEqual(profile.verdict, "insufficient")
        self.assertEqual(profile.queries_run, 2)


class TestRequirement(unittest.TestCase):
    def _req(self, name, body, **extra):
        rec = {
            "name": name,
            "notices": [{"title": name, "body_excerpt": body}],
            "team_text": extra.get("team_text", ""),
            "eligibility_text": "",
            "catalog_dept": extra.get("dept", ""),
        }
        return assess_requirement(rec)

    def test_explicit_mentor_requirement(self):
        out = self._req("中国高校计算机大赛-团体程序设计天梯赛",
                        "每支参赛队必须有至少1名教练，教练必须是本校正式教师。")
        self.assertEqual(out["mentor_dependency"], "required")

    def test_self_service_programming_contest(self):
        out = self._req("百度之星·程序设计大赛",
                        "具有正式全日制学籍的本科生均可登录大赛官网（astar.baidu.com）注册、报名、参赛。")
        self.assertEqual(out["mentor_dependency"], "self")
        self.assertEqual(out["difficulty"], "入门")

    def test_physical_prize_is_not_hardware(self):
        out = self._req("百度之星·程序设计大赛",
                        "各组前十名将有奖金/实物激励，第1名10000元。均可登录官网注册报名。")
        self.assertNotIn("涉及实物/硬件或实验环境", out["reasons"])

    def test_one_embedded_track_is_not_hardware_heavy(self):
        out = self._req("全国大学生软件测试大赛",
                        "赛项包括功能测试、性能测试、嵌入式测试和 AI 评测；"
                        "参赛学生须登录大赛平台完成报名。")
        self.assertNotEqual(out["mentor_dependency"], "required")
        self.assertTrue(any("部分赛项涉及嵌入式" in r for r in out["reasons"]))

    def test_robot_competition_needs_mentor(self):
        out = self._req("全国大学生智能汽车竞赛",
                        "比赛使用智能车整车、元器件和硬件调试，团队规模较大。")
        self.assertEqual(out["mentor_dependency"], "required")
        self.assertIn(out["difficulty"], ("较高", "很高"))

    def test_unknown_stays_pending(self):
        out = self._req("某个大学生竞赛", "现将有关事项通知如下。")
        self.assertEqual(out["mentor_dependency"], "pending")


if __name__ == "__main__":
    unittest.main(verbosity=2)
