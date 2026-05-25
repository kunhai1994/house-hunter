"""Beike (贝壳找房 / ke.com) adapter — KE Holdings 平台聚合。

跟 lianjia.py 完全同一个底层 HTML 模板（同公司，同套 CDN），仅 URL host 不同。
所以 KeAdapter 继承 LianjiaAdapter 大部分行为，只重写 URL 构造。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sources.site_adapters import register  # type: ignore
from sources.site_adapters.lianjia import (  # type: ignore
    LianjiaAdapter, _city_pinyin, _district_pinyin,
)


class KeAdapter(LianjiaAdapter):
    SITE_NAME = "ke"
    HOST = "ke.com"

    # ─── URL 构造 ───（覆盖 lianjia 的 host）
    def search_community_url(self, city: str, district: str | None) -> str | None:
        cp = _city_pinyin(city)
        if not cp:
            return None
        if district:
            dp = _district_pinyin(city, district)
            if dp:
                return f"https://{cp}.{self.HOST}/xiaoqu/{dp}/"
        return f"https://{cp}.{self.HOST}/xiaoqu/"

    def community_detail_url(self, community_id: str, city: str) -> str | None:
        cp = _city_pinyin(city)
        if not cp or not community_id:
            return None
        return f"https://{cp}.{self.HOST}/xiaoqu/{community_id}/"

    def listings_url(self, community_id: str, city: str) -> str | None:
        cp = _city_pinyin(city)
        if not cp or not community_id:
            return None
        return f"https://{cp}.{self.HOST}/zufang/c{community_id}/"


# 注册
register(KeAdapter())
