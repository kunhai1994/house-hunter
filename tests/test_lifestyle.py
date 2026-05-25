"""lifestyle_matcher 单元测试。"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from analyzers.lifestyle_matcher import (  # type: ignore
    merge_weights, lifestyle_score, get_extra_emphasis,
)


class TestMergeWeights(unittest.TestCase):
    def test_default_returns_uniform(self):
        w = merge_weights(["default"])
        # 所有顶层类别都是 1.0
        for v in w.values():
            self.assertEqual(v, 1.0)

    def test_homebody_lower_entertainment(self):
        w = merge_weights(["homebody"])
        self.assertGreater(w["shopping"], w["entertainment"])

    def test_nightlife_high_entertainment(self):
        w = merge_weights(["nightlife"])
        self.assertGreater(w["entertainment"], 1.0)

    def test_max_when_combining(self):
        """两个画像叠加 → 取每类的最大值（不会无限叠加）。"""
        w_h = merge_weights(["homebody"])
        w_n = merge_weights(["nightlife"])
        w_both = merge_weights(["homebody", "nightlife"])
        for cat in w_both:
            self.assertEqual(w_both[cat], max(w_h.get(cat, 0), w_n.get(cat, 0)))


class TestLifestyleScore(unittest.TestCase):
    def test_empty_scores(self):
        out = lifestyle_score({}, ["default"])
        self.assertEqual(out["score"], 0)

    def test_all_perfect(self):
        scores = {
            "shopping.big_supermarket": 10,
            "entertainment.cinema": 10,
            "transport.subway": 10,
        }
        out = lifestyle_score(scores, ["default"])
        self.assertEqual(out["score"], 100)

    def test_bias_towards_lifestyle(self):
        """同样的低分配套：商场党 vs 健身党，shopping 高时商场党分数应更高。"""
        scores = {
            "shopping.shopping_mall": 10,
            "entertainment.cinema": 5,
            "nature.park": 0,
        }
        s_shopping = lifestyle_score(scores, ["shopping_lover"])["score"]
        s_fitness = lifestyle_score(scores, ["fitness"])["score"]
        self.assertGreater(s_shopping, s_fitness)


class TestExtraEmphasis(unittest.TestCase):
    def test_single_woman_safety_emphasis(self):
        e = get_extra_emphasis(["single_woman"])
        self.assertGreater(e.get("safety", 1.0), 1.0)

    def test_homebody_no_emphasis(self):
        e = get_extra_emphasis(["homebody"])
        self.assertNotIn("safety", e)


if __name__ == "__main__":
    unittest.main()
