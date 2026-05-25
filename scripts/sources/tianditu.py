"""天地图 API 封装（v2 search service，第 3 fallback）。

文档：http://lbs.tianditu.gov.cn/server/search2.html
免费额度：个人开发者 1 万次/天（远超百度 5000 / 高德 100）
申请 Key：http://lbs.tianditu.gov.cn/authorization/authorization.html

API 端点统一为 GET /v2/search?postStr=<URL-encoded JSON>&type=query&tk=KEY

queryType:
  1 = 普通关键字搜索
  3 = 周边搜索（pointLonlat + queryRadius）
  7 = 行政区划搜索（specify cityname）

注意：lonlat 顺序是「经度,纬度」（与 amap 一致，与 baidu 相反）。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import http_get_json, cached, haversine, RateLimiter  # type: ignore


TIANDITU_BASE = "http://api.tianditu.gov.cn/v2/search"
_rate = RateLimiter(min_interval_s=0.05)

# 配额耗尽检测（与 baidu_map / amap 对称）
_QUOTA_FAIL_THRESHOLD = 3
_quota_fail_count = 0
_quota_exhausted = False


def is_quota_exhausted() -> bool:
    return _quota_exhausted


def _record_quota_fail() -> None:
    global _quota_fail_count, _quota_exhausted
    _quota_fail_count += 1
    if _quota_fail_count >= _QUOTA_FAIL_THRESHOLD:
        _quota_exhausted = True


def _record_success() -> None:
    global _quota_fail_count
    _quota_fail_count = 0


def _key() -> str | None:
    return os.environ.get("TIANDITU_API_KEY") or os.environ.get("TDT_KEY")


def _build_url(post_dict: dict) -> str | None:
    k = _key()
    if not k:
        return None
    post_str = json.dumps(post_dict, ensure_ascii=False, separators=(",", ":"))
    params = {"postStr": post_str, "type": "query", "tk": k}
    return f"{TIANDITU_BASE}?{urllib.parse.urlencode(params)}"


# ---------------------------------------------------------------------------
# 周边搜索（queryType=3）
# ---------------------------------------------------------------------------
@cached("tianditu_search_nearby", ttl_seconds=86400)
def search_nearby(query: str, lat: float, lng: float, radius_m: int,
                  page_size: int = 20) -> list[dict] | None:
    """周边 POI 搜索。

    Args:
      query: 关键词
      lat, lng: 中心点经纬度（与百度/高德接口一致：先 lat 后 lng）
      radius_m: 半径，米
      page_size: 单页大小
    """
    if _quota_exhausted:
        return None
    url = _build_url({
        "keyWord": query,
        "level": 12,
        "queryRadius": radius_m,
        "pointLonlat": f"{lng},{lat}",  # 天地图用 lng,lat
        "queryType": 3,
        "start": 0,
        "count": min(page_size, 50),
    })
    if not url:
        return None
    _rate.wait("tianditu")
    data = http_get_json(url, timeout=12)
    if not isinstance(data, dict):
        _record_quota_fail()
        return None
    status = (data.get("status") or {}).get("infocode")
    if status != 1000:
        _record_quota_fail()
        return None  # 1000 = 服务正常；其他 = 错误
    _record_success()
    pois = _normalize_pois(data.get("pois") or [])
    # 二次过滤：天地图偶尔越界，强制按 haversine 校验
    out = []
    for p in pois:
        if p.get("lat") is None or p.get("lng") is None:
            continue
        d = haversine(lat, lng, p["lat"], p["lng"])
        p["distance_m"] = round(d)
        if d <= radius_m * 1.05:
            out.append(p)
    out.sort(key=lambda x: x.get("distance_m", 1e9))
    return out


# ---------------------------------------------------------------------------
# 关键词搜索（queryType=1，全国范围）/ 行政区划搜索（queryType=7）
# ---------------------------------------------------------------------------
@cached("tianditu_search_region", ttl_seconds=86400)
def search_in_region(query: str, region: str, page_size: int = 20,
                     page_num: int = 0) -> list[dict] | None:
    """行政区划内搜索。

    region 是行政区划名（如 "深圳" 或 "深圳坪山区"）。
    天地图用 specify=区域代码，但纯文本也可以；这里用 queryType=7 + specify=region 文本。
    """
    if _quota_exhausted:
        return None
    url = _build_url({
        "keyWord": query,
        "queryType": 7,
        "start": page_num * page_size,
        "count": min(page_size, 50),
        "specify": region,
    })
    if not url:
        return None
    _rate.wait("tianditu")
    data = http_get_json(url, timeout=12)
    if not isinstance(data, dict):
        _record_quota_fail()
        return None
    status = (data.get("status") or {}).get("infocode")
    if status != 1000:
        _record_quota_fail()
        return None
    _record_success()
    return _normalize_pois(data.get("pois") or [])


# ---------------------------------------------------------------------------
# 地理编码（地址 → 经纬度）
# ---------------------------------------------------------------------------
@cached("tianditu_geocode", ttl_seconds=86400 * 7)
def geocode(address: str, city: str | None = None) -> dict | None:
    """地址 → 经纬度。

    天地图地理编码端点是 /geocoder?ds={"keyWord":...}&tk=KEY，跟 search 不同。
    """
    if _quota_exhausted:
        return None
    k = _key()
    if not k:
        return None
    full = address if not city else f"{city}{address}"
    ds = json.dumps({"keyWord": full}, ensure_ascii=False, separators=(",", ":"))
    url = f"http://api.tianditu.gov.cn/geocoder?{urllib.parse.urlencode({'ds': ds, 'tk': k})}"
    _rate.wait("tianditu")
    data = http_get_json(url, timeout=10)
    if not isinstance(data, dict):
        _record_quota_fail()
        return None
    status = data.get("status")
    if status != "0":  # 天地图地理编码 status=0 表示成功（与 search 不同）
        _record_quota_fail()
        return None
    _record_success()
    loc = data.get("location") or {}
    if "lat" not in loc or "lon" not in loc:
        return None
    try:
        return {
            "lat": float(loc["lat"]),
            "lng": float(loc["lon"]),
            "level": loc.get("level"),
        }
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 归一化 POI（让接口与 baidu_map / amap 一致）
# ---------------------------------------------------------------------------
def _normalize_pois(raw: list[dict]) -> list[dict]:
    """天地图 POI 归一化为统一格式。

    天地图原始字段：
      name, address, distance ("316m" 字符串), phone, lonlat ("lng,lat"),
      hotPointID (uid), poiType, source
    """
    out = []
    for r in raw:
        ll = (r.get("lonlat") or "").split(",")
        lat = lng = None
        if len(ll) == 2:
            try:
                lng = float(ll[0])
                lat = float(ll[1])
            except ValueError:
                pass
        # distance 可能是 "316m" 字符串
        dist_raw = r.get("distance")
        dist_int = None
        if dist_raw:
            s = str(dist_raw).rstrip("m").strip()
            try:
                dist_int = int(float(s))
            except ValueError:
                pass

        out.append({
            "uid": r.get("hotPointID"),
            "name": r.get("name"),
            "address": r.get("address"),
            "lat": lat,
            "lng": lng,
            "telephone": r.get("phone"),
            "distance_m": dist_int,
            "type": r.get("poiType"),
            "tag": "",  # 天地图无 tag 字段
            "source": "tianditu",
        })
    return out


def health() -> bool:
    """简单 ping：北京天安门附近能否搜公园。"""
    if not _key():
        return False
    r = search_nearby("公园", 39.90, 116.40, 5000, page_size=3)
    return r is not None and len(r) > 0
