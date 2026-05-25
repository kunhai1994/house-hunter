"""safety_checker 单元测试（不依赖外部网络）。"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from analyzers.safety_checker import (  # type: ignore
    all_keywords_with_severity, _match_keyword, _summarize, safety_score,
)


class TestKeywordCoverage(unittest.TestCase):
    def test_has_high_severity(self):
        kws = all_keywords_with_severity()
        sev_set = {sev for _, sev in kws}
        self.assertIn("high", sev_set)
        self.assertIn("medium", sev_set)
        self.assertIn("low", sev_set)

    def test_includes_violence(self):
        words = {kw for kw, _ in all_keywords_with_severity()}
        self.assertIn("凶案", words)
        self.assertIn("跳楼", words)
        self.assertIn("火灾", words)


class TestMatchKeyword(unittest.TestCase):
    def setUp(self):
        self.kws = [("凶案", "high"), ("入室", "medium"), ("噪音扰民", "low")]

    def test_high_priority_wins(self):
        kw, sev = _match_keyword("发生了凶案，还有噪音扰民", self.kws)
        self.assertEqual(kw, "凶案")
        self.assertEqual(sev, "high")

    def test_no_match(self):
        kw, sev = _match_keyword("一切都好", self.kws)
        self.assertIsNone(kw)


class TestSummarize(unittest.TestCase):
    def test_empty(self):
        s = _summarize({"high": 0, "medium": 0, "low": 0}, 0)
        self.assertIn("未查到", s)

    def test_with_findings(self):
        s = _summarize({"high": 1, "medium": 2, "low": 3}, 6)
        self.assertIn("高严重 1", s)
        self.assertIn("中等 2", s)


class TestSafetyScore(unittest.TestCase):
    def test_no_findings_floor(self):
        cfg = {"high_severity_penalty": 30, "medium_severity_penalty": 12,
               "low_severity_penalty": 4, "no_findings_floor": 80}
        # 没查到 → floor (80)
        self.assertEqual(safety_score({"high": 0, "medium": 0, "low": 0}, cfg), 80)

    def test_high_severity_penalty(self):
        cfg = {"high_severity_penalty": 30, "medium_severity_penalty": 12,
               "low_severity_penalty": 4, "no_findings_floor": 80}
        self.assertEqual(safety_score({"high": 1, "medium": 0, "low": 0}, cfg), 70)
        self.assertEqual(safety_score({"high": 2, "medium": 0, "low": 0}, cfg), 40)

    def test_score_floor_zero(self):
        cfg = {"high_severity_penalty": 30, "medium_severity_penalty": 12,
               "low_severity_penalty": 4, "no_findings_floor": 80}
        # 大量事件 → 不会 < 0
        self.assertEqual(safety_score({"high": 5, "medium": 0, "low": 0}, cfg), 0)


if __name__ == "__main__":
    unittest.main()
