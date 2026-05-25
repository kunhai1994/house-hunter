"""地理工具单元测试。"""

from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

from _common import haversine  # type: ignore


class TestHaversine(unittest.TestCase):
    def test_zero_distance(self):
        self.assertAlmostEqual(haversine(22.5, 113.9, 22.5, 113.9), 0, places=2)

    def test_known_distance(self):
        # 北京 → 上海，约 1067 km
        bj = (39.9042, 116.4074)
        sh = (31.2304, 121.4737)
        d = haversine(*bj, *sh)
        self.assertAlmostEqual(d / 1000, 1067, delta=20)

    def test_short_distance(self):
        # 1 km 范围内
        a = (22.5, 113.9)
        b = (22.5, 113.91)  # 大约 1 km
        d = haversine(*a, *b)
        self.assertGreater(d, 800)
        self.assertLess(d, 1300)


if __name__ == "__main__":
    unittest.main()
