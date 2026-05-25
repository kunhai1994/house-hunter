"""Jinja2 模板渲染测试 — 使用 mock payload 验证不报错。"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from reports.render import render_search, render_deep_dive  # type: ignore


def _mock_candidate(name: str, score: float) -> dict:
    return {
        "community": {
            "id": f"c-{name}",
            "name": name,
            "city": "深圳市",
            "district": "南山区",
            "lat": 22.5,
            "lng": 113.9,
            "address": "南山大道 100",
            "built_year": 2018,
            "property_company": "万科物业",
            "unit_count": 1500,
            "building_count": 8,
            "url": f"https://example.com/{name}",
        },
        "rental": {
            "url": f"https://example.com/{name}",
            "by_room": {
                "one_bedroom": {"avg": 6500, "min": 5800, "max": 7500, "count": 38},
                "two_bedroom": {"avg": 8500, "min": 7500, "max": 9800, "count": 52},
                "three_bedroom": {"avg": 11500, "min": 10000, "max": 13500, "count": 24},
                "shared_room": {"avg": 3800, "min": 3300, "max": 4500, "count": 67},
            },
            "total_listings": 181,
        },
        "poi_validation": {
            "must_have_satisfied": True,
            "missing": [],
            "poi_results": {
                "shopping.big_supermarket": [
                    {"name": "山姆", "distance_m": 800, "matched_brand": ["山姆"]},
                ],
                "shopping.shopping_mall": [
                    {"name": "海岸城", "distance_m": 200},
                ],
                "transport.subway": [
                    {"name": "后海站", "distance_m": 800},
                ],
            },
            "category_scores": {
                "shopping.big_supermarket": 9.0,
                "shopping.shopping_mall": 9.5,
                "transport.subway": 9.5,
            },
        },
        "sentiment": {
            "available": True,
            "total_notes": 36,
            "highlights": [
                {"title": "海岸城真的好住", "author": "abc", "likes": 1234,
                 "url": "https://www.xiaohongshu.com/explore/123", "desc": ""},
            ],
            "complaints": [
                {"title": "电梯有点慢", "author": "xyz", "likes": 234,
                 "url": "https://www.xiaohongshu.com/explore/456", "desc": ""},
            ],
            "by_dimension": {
                "物业": {"positive": 12, "negative": 2},
                "快递_外卖": {"positive": 14, "negative": 0},
            },
        },
        "safety": {
            "summary": "未查到风险事件（注意：未查到不代表没有发生）",
            "incidents": [],
            "by_severity": {"high": 0, "medium": 0, "low": 0},
            "xhs_available": True,
        },
        "score": {
            "total": score,
            "components": {"poi": 92, "rental": 100, "reputation": 86, "safety": 80, "commute": 0},
            "missing_must_have": [],
            "weights": {},
            "matched_room_key": "two_bedroom",
            "rental_note": "在预算内",
            "lifestyle_breakdown": {"shopping": 9.5, "entertainment": 9.0, "transport": 9.5},
        },
    }


def _mock_payload(intent: str = "search", n: int = 3) -> dict:
    return {
        "requirement": {
            "intent": intent,
            "city": "深圳市",
            "district": "南山区",
            "area": None,
            "rooms": 2,
            "halls": 1,
            "area_min_sqm": 65,
            "area_max_sqm": 75,
            "budget": {"type": "rent", "max_per_month": 9000},
            "lifestyle_profile": ["shopping_lover"],
            "must_have_pois": [
                {"category": "shopping.big_supermarket", "label": "大型超市", "radius_m": 3000, "min_count": 1, "must_have_brand": []},
                {"category": "shopping.shopping_mall", "label": "购物中心", "radius_m": 3000, "min_count": 1, "must_have_brand": []},
            ],
            "nice_to_have_pois": [
                {"category": "transport.subway", "label": "地铁站", "radius_m": 1000, "min_count": 1, "must_have_brand": []},
            ],
        },
        "candidates": [_mock_candidate(f"小区{i+1}", 90 - i * 5) for i in range(n)],
        "compromises": [],
        "candidate_source": "lianjia_full",
        "poi_specs_by_cat": {
            "shopping.big_supermarket": {"label": "大型超市", "radius_m": 3000},
            "shopping.shopping_mall": {"label": "购物中心", "radius_m": 3000},
            "transport.subway": {"label": "地铁站", "radius_m": 1000},
        },
        "lifestyle_recommendations": {
            "🛒 商场党 / 购物党": {
                "community": {"name": "小区1"},
                "score": {"total": 90},
                "recommended_reason": "shopping 9.5/10",
            },
        },
        "rental_listing_url": "https://sz.lianjia.com/zufang/nanshan/",
        "total_xhs_notes": 108,
    }


class TestSearchRender(unittest.TestCase):
    def test_renders_without_error(self):
        md = render_search(_mock_payload(intent="search", n=5))
        self.assertIn("租房报告", md)
        self.assertIn("Top 1", md)
        self.assertIn("小区1", md)

    def test_includes_lifestyle(self):
        md = render_search(_mock_payload(intent="search", n=3))
        self.assertIn("shopping_lover", md)


class TestDeepDiveRender(unittest.TestCase):
    def test_renders_without_error(self):
        md = render_deep_dive(_mock_payload(intent="research", n=5))
        self.assertIn("年轻人租房调研", md)
        self.assertIn("横向对比", md)
        self.assertIn("配套盘点", md)

    def test_includes_lifestyle_picks(self):
        md = render_deep_dive(_mock_payload(intent="research", n=3))
        self.assertIn("商场党", md)


if __name__ == "__main__":
    unittest.main()
