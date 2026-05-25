"""Site adapters — 多房产平台抓取的统一接口与数据模型。

每个房产平台一个 adapter 模块，实现 SiteAdapter 协议：
  lianjia.py / ke.py / ziroom.py / anjuke.py / _58.py / fang.py

业务层（rental.py 等）只跟 CommunityInfo / Listing / PriceInfo 三个 dataclass 交互，
不感知具体数据来源。加新站点 = 加一个 adapter 文件，不动业务代码。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Protocol, runtime_checkable


# ───────────────────────── 统一数据 schema ─────────────────────────
@dataclass
class CommunityInfo:
    """归一化的小区基础信息（任何站点都映射到这个 schema）"""
    name: str
    city: str
    source: str                       # "lianjia" / "ke" / "ziroom" / ...
    source_id: str | None = None      # 该平台上的小区 id
    url: str | None = None
    district: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    built_year: int | None = None     # 建成年份
    building_count: int | None = None # 楼栋数
    unit_count: int | None = None     # 户数
    property_company: str | None = None  # 物业公司
    rent_avg: int | None = None       # 平均月租（仅在搜索列表场景填）
    listings_count: int | None = None # 在租挂牌量

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Listing:
    """单条挂牌房源"""
    listing_id: str
    community_name: str
    source: str
    url: str | None = None
    rooms: int | None = None              # 几室
    halls: int | None = None              # 几厅
    area_sqm: float | None = None
    floor_desc: str | None = None         # "中楼层/共 18 层"
    facing: str | None = None             # 朝向
    decoration: str | None = None
    rent_yuan_per_month: int | None = None
    is_shared_room: bool = False          # 是否合租主卧
    posted_date: str | None = None        # ISO

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PriceInfo:
    """小区价格汇总（按户型分布）"""
    community_id: str
    source: str
    url: str | None = None
    by_room: dict = field(default_factory=dict)
    # by_room = {
    #   "one_bedroom":   {"avg": ..., "min": ..., "max": ..., "count": ...},
    #   "two_bedroom":   {...},
    #   "three_bedroom": {...},
    #   "shared_room":   {...},
    # }
    total_listings: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# ───────────────────────── adapter 协议 ─────────────────────────
@runtime_checkable
class SiteAdapter(Protocol):
    """每个站点 adapter 必须实现的接口。"""

    SITE_NAME: str           # "lianjia" / "ke" / ...
    SUPPORTED_CITIES: set[str]   # 支持的城市名集合（"深圳市" 等）

    # URL 构造
    def search_community_url(self, city: str, district: str | None) -> str | None:
        """构造"按区搜索小区列表"页 URL。"""
        ...

    def community_detail_url(self, community_id: str, city: str) -> str | None:
        """构造小区详情页 URL。"""
        ...

    def listings_url(self, community_id: str, city: str) -> str | None:
        """构造小区房源挂牌列表 URL。"""
        ...

    # HTML 解析
    def parse_search(self, html: str, city: str) -> list[CommunityInfo]:
        """从搜索/列表 HTML 解析出小区清单。"""
        ...

    def parse_community_detail(self, html: str, community_id: str, city: str) -> CommunityInfo | None:
        """从详情 HTML 解析出单个小区的元数据（含 built_year）。"""
        ...

    def parse_listings(self, html: str, community_id: str, city: str) -> PriceInfo:
        """从挂牌列表 HTML 聚合出价格分布。"""
        ...


# ───────────────────────── adapter 注册中心 ─────────────────────────
_ADAPTERS: dict[str, SiteAdapter] = {}


def register(adapter: SiteAdapter) -> None:
    """每个 adapter 文件在 module 顶层调一次注册自己。"""
    _ADAPTERS[adapter.SITE_NAME] = adapter


def get_adapter(name: str) -> SiteAdapter | None:
    return _ADAPTERS.get(name)


def all_adapters() -> list[SiteAdapter]:
    """按 fallback 优先级返回所有 adapter（用户决策：贝壳首选）。

    顺序：
      1. ke (贝壳) — 用户指定首选；跟 lianjia 共数据库但 URL 入口不同
      2. lianjia (链家) — 数据等同贝壳，作 ke 的另一入口
      3. anjuke (安居客) — 独立数据源，列表区准（实测 25 个龙岗）
      4. ziroom (自如) — 长租公寓
      5. 58 (58同城) — 个人房东直租
      6. fang (房天下) — 老牌门户
    """
    order = ["ke", "lianjia", "anjuke", "ziroom", "58", "fang"]
    return [_ADAPTERS[k] for k in order if k in _ADAPTERS]


def _autoload_adapters() -> None:
    """import 所有已知 adapter 模块，触发它们的 register() 调用。"""
    # 异常隔离：单个 adapter 加载失败不影响其他
    import importlib
    for mod_name in ["lianjia", "ke", "ziroom", "anjuke", "_58", "fang"]:
        try:
            importlib.import_module(f"sources.site_adapters.{mod_name}")
        except ImportError:
            # adapter 可能尚未实现，安全跳过
            pass
        except Exception as e:
            import logging
            logging.getLogger("site_adapters").warning(
                "Failed to load adapter %s: %s", mod_name, e
            )


_autoload_adapters()
