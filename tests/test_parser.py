"""parsers/ 单元测试。"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from parsers.requirement_parser import (  # type: ignore
    detect_lifestyle_profiles, expand_poi_category,
    normalize_poi_spec, validate_and_normalize,
)
from parsers.city_resolver import normalize, resolve  # type: ignore


class TestLifestyleDetection(unittest.TestCase):
    def test_homebody(self):
        self.assertIn("homebody", detect_lifestyle_profiles("我想宅在家点外卖"))

    def test_nightlife(self):
        self.assertIn("nightlife", detect_lifestyle_profiles("喜欢酒吧 livehouse 蹦迪"))

    def test_shopping_lover(self):
        self.assertIn("shopping_lover", detect_lifestyle_profiles("周末喜欢逛商场看 IMAX"))

    def test_single_woman(self):
        self.assertIn("single_woman", detect_lifestyle_profiles("我是女生独居 重视安全"))

    def test_multiple(self):
        profiles = detect_lifestyle_profiles("健身党 + 商场党")
        self.assertIn("fitness", profiles)
        self.assertIn("shopping_lover", profiles)

    def test_default_when_no_match(self):
        self.assertEqual(detect_lifestyle_profiles("搬家"), ["default"])


class TestPOICategoryExpansion(unittest.TestCase):
    def test_known_category(self):
        exp = expand_poi_category("shopping.big_supermarket")
        self.assertIsNotNone(exp)
        self.assertEqual(exp["label"], "大型超市")
        # v2 schema: primary_keywords + brand_keywords 分开
        self.assertGreater(len(exp["primary_keywords"]), 0,
                           "应至少有 1 个 primary_keyword 调 API")
        self.assertGreater(len(exp["brand_keywords"]), 5,
                           "大型超市应有 > 5 个品牌（山姆/沃尔玛/...）")
        self.assertEqual(exp["default_radius_m"], 3000)

    def test_unknown_category(self):
        self.assertIsNone(expand_poi_category("foo.bar"))
        self.assertIsNone(expand_poi_category("shopping"))  # 缺子类


class TestCityResolution(unittest.TestCase):
    def test_whitelist_city(self):
        out = normalize("深圳")
        self.assertEqual(out["city"], "深圳市")

    def test_district_as_city(self):
        out = normalize("坪山")
        self.assertEqual(out["city"], "深圳市")
        self.assertEqual(out["district"], "坪山区")

    def test_off_whitelist_city_keeps_input(self):
        """白名单外的城市应该原样保留 + 自动补「市」字。"""
        out = normalize("清远")
        self.assertEqual(out["city"], "清远市")

    def test_off_whitelist_no_double_suffix(self):
        out = normalize("清远市")
        self.assertEqual(out["city"], "清远市")  # 不重复加「市」

    def test_resolve_from_text(self):
        out = resolve("我想在坪山区找房")
        self.assertIsNotNone(out)
        self.assertEqual(out["city"], "深圳市")
        self.assertEqual(out["district"], "坪山区")


class TestPOISpecNormalization(unittest.TestCase):
    def test_normalize_with_keywords(self):
        spec = normalize_poi_spec({
            "category": "shopping.big_supermarket",
            "match_keywords": ["山姆"],
            "min_count": 1,
            "radius_m": 3000,
        })
        self.assertEqual(spec["keywords"], ["山姆"])
        self.assertEqual(spec["radius_m"], 3000)

    def test_normalize_uses_default_keywords(self):
        spec = normalize_poi_spec({
            "category": "shopping.shopping_mall",
            "min_count": 1,
        })
        # v2: search_keywords 是少量泛用词（如「购物中心」），不再每个品牌都搜
        self.assertGreater(len(spec["search_keywords"]), 0)
        # brand_keywords 应当含品牌列表（万象城/万达等）
        self.assertGreater(len(spec["brand_keywords"]), 5)
        # keywords 字段保留作 backward compat（= search_keywords）
        self.assertEqual(spec["keywords"], spec["search_keywords"])

    def test_brand_filter(self):
        spec = normalize_poi_spec({
            "category": "entertainment.cinema",
            "must_have_brand": ["IMAX"],
        })
        self.assertEqual(spec["must_have_brand"], ["IMAX"])


class TestRequirementNormalization(unittest.TestCase):
    def test_minimal_search(self):
        req = {"city": "坪山", "raw": "坪山找房", "must_have_pois": []}
        out = validate_and_normalize(req)
        self.assertEqual(out["city"], "深圳市")
        self.assertEqual(out["district"], "坪山区")
        self.assertEqual(out["intent"], "search")
        self.assertEqual(out["top_n"], 5)

    def test_research_default_topn(self):
        req = {"intent": "research", "city": "深圳", "raw": "南山调研", "must_have_pois": []}
        out = validate_and_normalize(req)
        self.assertEqual(out["top_n"], 8)

    def test_no_city_raises(self):
        req = {"raw": "找个房子", "must_have_pois": []}
        with self.assertRaises(ValueError):
            validate_and_normalize(req)


if __name__ == "__main__":
    unittest.main()
