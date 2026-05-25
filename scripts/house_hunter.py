#!/usr/bin/env python3
"""house-hunter 主引擎 — 编排全流程。

输入（任选其一）：
  --requirement-json '<JSON 字符串>'
  --requirement-file path/to/req.json

输出：
  Markdown 报告（默认保存到 ~/Documents/House-Hunter/）
  + JSON 原始数据（同目录，*-raw.json）
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from _common import (  # type: ignore
    REPORT_DIR, set_cache_dir, find_skill_root, parallel_map,
    info, ok, fail, warn,
)
from parsers.requirement_parser import validate_and_normalize  # type: ignore
from parsers.city_resolver import validate_via_geocoding  # type: ignore
from sources import baidu_map, amap, rental, xhs  # type: ignore
from sources.community_search import find_candidates  # type: ignore
from analyzers.poi_validator import validate_community  # type: ignore
from analyzers.rental_analyzer import analyze_community  # type: ignore
from analyzers.sentiment_aggregator import aggregate as aggregate_reviews  # type: ignore
from analyzers.safety_checker import check_community as check_safety  # type: ignore
from analyzers.commute_simulator import simulate as simulate_commute  # type: ignore
from analyzers.community_scorer import score as compute_score  # type: ignore
from reports.render import render_search, render_deep_dive  # type: ignore


def build_pipeline(requirement: dict, max_candidates: int = 6) -> dict:
    """端到端：候选生成 → 多源采集 → 评分 → 排序。"""
    city = requirement["city"]
    district = requirement.get("district")
    area = requirement.get("area")
    top_n = int(requirement.get("top_n", 5))

    # 1. 候选小区
    info(f"[1/5] 候选生成（{city} {district or ''}{(' / 中心点:' + area) if area else ''}）")
    candidates_raw, candidate_source = find_candidates(
        city, district, area, limit=max_candidates,
        search_radius_m=requirement.get("search_radius_m"),
    )
    if not candidates_raw:
        warn(f"未找到任何候选小区（city={city} district={district}）")
        warn("可能原因：城市名不在地图覆盖、API key 配额、网络。")
        return {"requirement": requirement, "candidates": [], "candidate_source": "empty"}
    info(f"  → 来源 {candidate_source}，{len(candidates_raw)} 个候选")

    # 1b. 补充经纬度（链家有时不带；百度 POI 来源带）
    candidates_raw = parallel_map(_ensure_latlng, candidates_raw, max_workers=4, timeout=300)
    candidates_raw = [c for c in candidates_raw if c]

    # 1c. 区过滤：剔除明显跨区候选（链家 /xiaoqu/{district}/ 有时混入跨区小区）
    # area 模式（中心点 + 半径）天然在区内，跳过过滤
    if district and not area:
        before_filter = len(candidates_raw)
        candidates_raw = _filter_by_district(candidates_raw, district)
        if len(candidates_raw) < before_filter:
            info(f"  → 区过滤剔除 {before_filter - len(candidates_raw)} 个跨区候选，剩 {len(candidates_raw)}")
        if not candidates_raw:
            warn(f"区过滤后无候选（{candidate_source} 列表全跨区/无 address）— 改走百度 POI nearby 兜底")
            # 不再回退「不筛选原列表」（会让跨区小区污染报告）
            # 改用 area={district} 走中心点 + 5km nearby，POI 坐标天然在区内
            candidates_raw, candidate_source = find_candidates(
                city, district=None, area=district, limit=max_candidates,
                search_radius_m=5000,
            )
            candidates_raw = parallel_map(_ensure_latlng, candidates_raw, max_workers=4, timeout=300)
            candidates_raw = [c for c in candidates_raw if c]

    # 2. 串行采集各维度（max_workers=1：parallel_map 多线程有 race condition）
    info(f"[2/5] 串行采集各维度（POI / 租金 / 口碑 / 安全）共 {len(candidates_raw)} 个候选")
    enriched = parallel_map(
        lambda c: _enrich_one(c, requirement),
        candidates_raw,
        max_workers=1,
        timeout=1500,
    )
    none_count = sum(1 for e in enriched if e is None)
    enriched = [e for e in enriched if e]
    info(f"  → enriched {len(enriched)} / {len(candidates_raw)} candidates (None: {none_count})")

    # 3. 评分
    info(f"[3/5] 综合评分")
    for e in enriched:
        e["score"] = compute_score(
            community=e["community"],
            poi_validation=e["poi_validation"],
            rental_info=e.get("rental") or {},
            sentiment=e.get("sentiment") or {},
            safety=e.get("safety") or {},
            commute=e.get("commute"),
            requirement=requirement,
        )

    # 4. 排序 + Top N
    info(f"[4/5] 排序，取 Top {top_n}")
    enriched.sort(key=lambda x: x["score"]["total"], reverse=True)
    top = enriched[:top_n]
    compromises = [
        e for e in enriched[top_n:]
        if e["score"]["missing_must_have"] and e["score"]["total"] > 50
    ][:3]

    # 5. 准备 spec map（给模板用）
    poi_specs_by_cat: dict[str, dict] = {}
    for spec in (requirement.get("must_have_pois") or []) + (requirement.get("nice_to_have_pois") or []):
        poi_specs_by_cat[spec["category"]] = spec

    # Lifestyle 推荐（Case B 用）
    lifestyle_recs = _build_lifestyle_recs(enriched)

    return {
        "requirement": requirement,
        "candidates": top,
        "compromises": compromises,
        "candidate_source": candidate_source,
        "candidate_source_label": _source_label(candidate_source),
        "poi_specs_by_cat": poi_specs_by_cat,
        "lifestyle_recommendations": lifestyle_recs,
        "rental_listing_url": _build_rental_listing_url(city, district),
        "total_xhs_notes": sum(
            (e.get("sentiment") or {}).get("total_notes", 0) for e in enriched
        ),
    }


def _source_label(source: str | None) -> str:
    """把 candidate_source 翻译成报告里显示的友好名。"""
    if not source:
        return "未知"
    table = {
        "ke_full":          "贝壳找房 (ke.com)",
        "lianjia_full":     "链家 (lianjia.com)",
        "anjuke_full":      "安居客 (anjuke.com)",
        "ziroom_full":      "自如 (ziroom.com)",
        "58_full":          "58 同城 (58.com)",
        "fang_full":        "房天下 (fang.com)",
        "baidu_map_poi":    "百度地图 POI",
        "amap_poi":         "高德地图 POI",
        "tianditu_poi":     "天地图 POI",
        "empty":            "无候选",
    }
    return table.get(source, source)


def _ensure_latlng(c: dict) -> dict | None:
    """补充坐标 + 元数据（按 source 调对应 adapter）。

    永不剔除候选（即使 geocode 失败也保留 — POI 校验会 graceful degrade）。
    """
    # 先尝试通过 adapter 详情页拿元数据（含 lat/lng 如果该源提供）
    source = c.get("source") or ("lianjia" if _is_lianjia_id(c) else None)
    needs_enrich = (
        c.get("built_year") is None
        or c.get("lat") is None
        or c.get("lng") is None
    )
    if source and needs_enrich:
        _enrich_community_basics(c)

    # geocode 兜底（如果详情页没给 lat/lng — 比如 anjuke）
    if c.get("lat") is None or c.get("lng") is None:
        name = c.get("name") or ""
        city = c.get("city") or ""
        addr = c.get("address") or ""
        # 优先用具体地址 geocode（精度更高），失败再用小区名
        target = f"{city}{addr}" if addr else f"{city}{name}"
        geo = baidu_map.geocode(target, city) or amap.geocode(target, city)
        if not geo and addr:
            # 地址 geocode 失败，回退到小区名
            geo = baidu_map.geocode(f"{city}{name}", city) or amap.geocode(f"{city}{name}", city)
        if geo:
            c["lat"] = geo["lat"]
            c["lng"] = geo["lng"]
    return c


def _filter_by_district(candidates: list[dict], target_district: str) -> list[dict]:
    """剔除明显跨区的候选。

    保留逻辑（strict 模式，宁可漏不可错）：
      - 有 address 且含 district → 保留
      - 有 address 但不含 → 剔除（明确跨区）
      - 无 address → 剔除（无法判断 = 不要冒污染报告的险，让 fallback 走 POI nearby 兜底）

    历史教训：anjuke search 列表 address 常为空，老版本「无 address 保留」导致
    跨区小区进报告（如搜光明区返回新湖路/笋岗东路等跨区小区）。
    """
    if not target_district:
        return candidates
    short = target_district.rstrip("区县市")
    out = []
    for c in candidates:
        addr = c.get("address") or ""
        if not addr:
            continue
        if target_district in addr or (short and short in addr):
            out.append(c)
    return out


def _enrich_community_basics(c: dict) -> bool:
    """根据 community.source 调对应 adapter 的详情页解析，补元数据。

    - lianjia/ke：用 rental.community_basic_info（共享 lianjia HTML 模板）
    - anjuke/58/fang/ziroom：调 housing_bridge 抓详情 + 对应 adapter parse
    - amap_poi / baidu_map_poi / tianditu_poi（地图 POI 兜底）：候选无 detail URL，
      → 通过 ke/lianjia 关键词搜小区名 → 拿 ke 详情 → 补建成年份/物业/户数

    返 True 表示拿到至少一个元数据字段。
    """
    source = c.get("source")

    # 1. 链家/贝壳 直接路由
    if source == "lianjia" or source == "ke" or (not source and _is_lianjia_id(c)):
        basic = rental.community_basic_info(c["id"], c.get("city", ""))
        if not basic:
            return False
        return _merge_basic(c, basic, is_dict=True)

    # 2. 地图 POI 兜底来源 → ke 关键词搜补
    if source and source.endswith("_poi"):
        return _resolve_via_ke_search(c)

    # 3. 其他 adapter 来源（anjuke / 58 / fang / ziroom）
    if source:
        try:
            from sources import housing_bridge  # type: ignore
            from sources.site_adapters import get_adapter  # type: ignore
            adapter = get_adapter(source)
            if not adapter:
                return False
            url = adapter.community_detail_url(c["id"], c.get("city", ""))
            if not url:
                return False
            html = housing_bridge.fetch_html(url)
            if not html:
                return False
            info = adapter.parse_community_detail(html, c["id"], c.get("city", ""))
            if not info:
                return False
            return _merge_basic(c, info, is_dict=False)
        except Exception:
            return False

    return False


def _merge_basic(c: dict, basic, is_dict: bool) -> bool:
    """把 basic（dict or CommunityInfo）的元数据 merge 到 c。"""
    def _g(k):
        return basic.get(k) if is_dict else getattr(basic, k, None)
    for key in ("built_year", "property_company", "unit_count", "building_count", "address"):
        v = _g(key)
        if v is not None:
            c[key] = v
    lat, lng = _g("lat"), _g("lng")
    if lat and lng:
        c["lat"] = lat
        c["lng"] = lng
    nm = _g("name")
    if nm and not c.get("name"):
        c["name"] = nm
    return True


def _best_name_match(target: str, pairs: list) -> str | None:
    """三层匹配：精确 → 双向 substring → 去后缀 fuzzy → difflib 相似度 > 0.7。

    pairs: [(id, name), ...]
    返回最匹配的 id，没匹配返 None。
    """
    import re as _re
    target = target.strip()

    # 1. 精确
    for cid, cname in pairs:
        if cname.strip() == target:
            return cid

    # 2. 双向 substring（候选名含搜索名 or 反之）
    for cid, cname in pairs:
        cn = cname.strip()
        if target in cn or cn in target:
            return cid

    # 3. 去常见后缀模糊（"1期 / 北区 / 一区 / 二期"）
    suffix_pattern = r'(\d+期|[一二三四五]期|[东南西北中]区|[一二三四五]区|花园|小区|公寓|苑|城)$'
    base = _re.sub(suffix_pattern, '', target).strip()
    if base and base != target and len(base) >= 2:
        for cid, cname in pairs:
            cn_base = _re.sub(suffix_pattern, '', cname.strip()).strip()
            if cn_base == base or (base in cn_base) or (cn_base in base):
                return cid

    # 4. difflib 相似度兜底（取最相似的，要求 ratio > 0.7）
    try:
        from difflib import SequenceMatcher
        scored = [
            (SequenceMatcher(None, target, cn.strip()).ratio(), cid)
            for cid, cn in pairs
        ]
        scored.sort(reverse=True)
        if scored and scored[0][0] > 0.7:
            return scored[0][1]
    except Exception:
        pass

    return None


def _resolve_via_ke_search(c: dict) -> bool:
    """对地图 POI 来源候选：用关键词搜补元数据。

    数据源优先级（贝壳第一硬约束）：
      1. ke /xiaoqu/rs{name}/   ← 贝壳，首选
      2. lianjia /xiaoqu/rs{name}/   ← 链家 fallback（同公司同数据）
      3. anjuke /community/?kw={name}   ← 独立数据源，覆盖 lianjia 没收录的小区
    """
    try:
        from sources import housing_bridge  # type: ignore
        import urllib.parse, re as _re
        name = c.get("name") or ""
        city = c.get("city") or "深圳市"
        if not name:
            return False

        from sources.site_adapters.lianjia import _city_pinyin  # type: ignore
        cp = _city_pinyin(city)
        if not cp:
            return False

        # 1+2. 贝壳/链家 关键词搜（共享 HTML 模板）
        for host in ("ke.com", "lianjia.com"):
            search_url = f"https://{cp}.{host}/xiaoqu/rs{urllib.parse.quote(name)}/"
            html = housing_bridge.fetch_html(search_url)
            if not html:
                continue
            pairs = _re.findall(
                r'<li[^>]*xiaoquListItem[^>]*data-id="(\d+)"[^>]*>'
                r'(?:.{0,500}?)<div class="title">\s*<a[^>]*>([^<]+)</a>',
                html, _re.DOTALL,
            )
            if not pairs:
                pairs = _re.findall(
                    r'href="/xiaoqu/(\d+)/?"[^>]*(?:title|alt)="([^"]+)"',
                    html,
                )
            if not pairs:
                continue
            best_id = _best_name_match(name, pairs)
            if not best_id:
                continue
            basic = rental.community_basic_info(best_id, city)
            if basic and (basic.get("built_year") or basic.get("property_company")):
                c["ke_resolved_id"] = best_id
                _merge_basic(c, basic, is_dict=True)
                return True

        # 3. anjuke 关键词搜（独立数据源，覆盖 ke/lianjia 没收录的小区）
        # 例如光明新区的"光明新村""电建地产洺悦府"链家没收录但 anjuke 有
        anjuke_url = f"https://shenzhen.anjuke.com/community/?from=navigation&kw={urllib.parse.quote(name)}"
        # 注：anjuke host 是 shenzhen.anjuke.com（全拼音），跟 ke/lianjia 不同
        if city != "深圳市":
            # 其他城市的 anjuke 子域映射
            from sources.site_adapters.anjuke import _CITY_PINYIN as _aj_cp
            aj_host = _aj_cp.get(city)
            if not aj_host:
                return False
            anjuke_url = f"https://{aj_host}.anjuke.com/community/?from=navigation&kw={urllib.parse.quote(name)}"

        html = housing_bridge.fetch_html(anjuke_url)
        if not html:
            return False
        # 解析 anjuke (id, name) 对（从 img alt）
        pairs = _re.findall(
            r'/community/view/(\d+)"[^>]*>.{0,300}?<img\s+alt="([^"]+)"',
            html, _re.DOTALL,
        )
        if not pairs:
            return False
        best_id = _best_name_match(name, pairs)
        if not best_id:
            return False
        # 调 anjuke 详情拿建成年份
        from sources.site_adapters import get_adapter  # type: ignore
        ak = get_adapter("anjuke")
        detail_url = ak.community_detail_url(best_id, city)
        detail_html = housing_bridge.fetch_html(detail_url)
        if not detail_html:
            return False
        info = ak.parse_community_detail(detail_html, best_id, city)
        if not info or not info.built_year:
            return False
        # anjuke 没 lianjia 数字 id，rental_id 没法用；只补元数据
        _merge_basic(c, info, is_dict=False)
        c["anjuke_resolved_id"] = best_id  # 标记来源（用于报告显示）
        return True
    except Exception:
        return False


def _is_lianjia_id(community: dict) -> bool:
    """判断 community 是否来自链家（id 是纯数字）。

    候选来源 id 格式：
      - 链家：纯数字字符串，如 "2123"
      - 百度兜底：'baidu_map_poi-<uid>' / 'amap_poi-<uid>' / 'tianditu_poi-<uid>'
    """
    cid = community.get("id")
    return bool(cid) and str(cid).isdigit()


def _enrich_one(community: dict, requirement: dict) -> dict | None:
    if not community.get("name"):
        return None
    out: dict[str, Any] = {"community": community}

    # 注：community_basic_info 在 _ensure_latlng 阶段已调用过（避免重复请求）

    # POI 校验
    out["poi_validation"] = validate_community(
        community,
        requirement.get("must_have_pois") or [],
        requirement.get("nice_to_have_pois") or [],
    )

    # 租金：优先用 ke_resolved_id（地图 POI 候选 + ke 搜索补充得来的真实 ke id），
    # 否则看 community.id 是否本身就是 ke/lianjia 数字 id
    rental_id = community.get("ke_resolved_id")
    if not rental_id and _is_lianjia_id(community) and community.get("source") in (None, "lianjia", "ke"):
        rental_id = community["id"]
    if rental_id:
        out["rental"] = analyze_community(rental_id, community.get("city"))
    else:
        out["rental"] = {"available": False}

    # 小红书口碑
    out["sentiment"] = aggregate_reviews(
        community["name"],
        community.get("city", ""),
        limit=15,
    )

    # 安全
    out["safety"] = check_safety(community["name"], community.get("city", ""))

    # 通勤（如果用户指定了目的地）
    dest = requirement.get("commute_destination")
    if dest and community.get("lat"):
        out["commute"] = simulate_commute(
            community["lat"], community["lng"], dest, community.get("city"),
        )

    return out


def _build_rental_listing_url(city: str, district: str | None) -> str | None:
    """贝壳第一（rental.lianjia_zufang_url 现在默认 host='ke.com'）"""
    if rental.is_lianjia_supported(city):
        return rental.lianjia_zufang_url(city, district)
    return None


def _build_lifestyle_recs(enriched: list[dict]) -> dict:
    """简单 lifestyle 推荐：每个 profile 取 lifestyle_breakdown 最高分的 community。

    注意：类别最高分 < MIN_SCORE_THRESHOLD 时不推荐（避免「transport=0/10 但被推荐为通勤党」的乌龙）。
    """
    MIN_SCORE_THRESHOLD = 5.0  # 类别得分 ≥5/10 才有推荐意义
    recs: dict[str, dict] = {}
    if not enriched:
        return {}
    # 按 top-category 强项推荐
    by_top = {"shopping": [], "entertainment": [], "transport": [], "nature": []}
    for e in enriched:
        breakdown = e["score"].get("lifestyle_breakdown") or {}
        for top in by_top:
            if top in breakdown:
                by_top[top].append((breakdown[top], e))
    label_map = {
        "shopping": "🛒 商场党 / 购物党",
        "entertainment": "🎬 娱乐党",
        "transport": "🚇 通勤党",
        "nature": "🌳 自然党",
    }
    for top, items in by_top.items():
        if not items:
            continue
        items.sort(key=lambda x: x[0], reverse=True)
        top_score, top_pick = items[0]
        # 关键修复：类别得分太低时不推荐（避免「transport=0/10 推荐通勤党」）
        if top_score < MIN_SCORE_THRESHOLD:
            continue
        recs[label_map[top]] = {
            "community": top_pick["community"],
            "score": top_pick["score"],
            "recommended_reason": f"{top} 类配套强（{round(top_score, 1)}/10）",
        }
    return recs


def main() -> int:
    parser = argparse.ArgumentParser(description="house-hunter 主引擎")
    parser.add_argument("--requirement-json", help="结构化需求 JSON 字符串")
    parser.add_argument("--requirement-file", help="需求 JSON 文件路径")
    parser.add_argument("--save-dir", default=REPORT_DIR, help="报告保存目录")
    parser.add_argument("--cache-dir", default=None, help="缓存目录覆盖")
    parser.add_argument("--max-candidates", type=int, default=6, help="候选小区最大数（影响速度）")
    parser.add_argument("--json", action="store_true", help="同时输出 JSON 原始数据")
    args = parser.parse_args()

    if args.cache_dir:
        set_cache_dir(args.cache_dir)

    # 读取需求
    if args.requirement_file:
        with open(args.requirement_file, "r", encoding="utf-8") as f:
            req_raw = json.load(f)
    elif args.requirement_json:
        req_raw = json.loads(args.requirement_json)
    else:
        fail("必须传 --requirement-json 或 --requirement-file")
        return 2

    # 校验 + 标准化
    try:
        requirement = validate_and_normalize(req_raw)
    except Exception as e:
        fail(f"需求校验失败: {e}")
        return 2

    # 城市白名单外校验（用地图 API ping 一下）
    if not rental.is_lianjia_supported(requirement["city"]):
        info(f"城市 {requirement['city']} 不在链家增强白名单 — 走百度地图 POI fallback")
        # 用 geocode 校验是否真实存在
        validation = validate_via_geocoding(requirement["city"])
        if not validation:
            fail(f"地图 API 无法识别城市 {requirement['city']!r}，请检查输入或 API key")
            return 3

    info(f"开始查询：intent={requirement['intent']} city={requirement['city']} "
         f"district={requirement.get('district')} top_n={requirement['top_n']}")

    t0 = time.time()
    payload = build_pipeline(requirement, max_candidates=args.max_candidates)
    elapsed = time.time() - t0
    info(f"[5/5] 渲染报告（耗时 {elapsed:.1f}s）")

    # 渲染
    if not payload["candidates"]:
        warn("无候选小区，跳过渲染。")
        return 1

    if requirement["intent"] == "research":
        md = render_deep_dive(payload)
    else:
        md = render_search(payload)

    # 保存
    os.makedirs(args.save_dir, exist_ok=True)
    topic = _build_topic(requirement)
    today = dt.datetime.now().strftime("%Y%m%d")
    md_path = os.path.join(args.save_dir, f"{topic}-{today}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    ok(f"报告已保存：{md_path}")

    if args.json:
        # 转 JSON-safe（dataclass / 自定义类一般没有，这里直接 dump）
        json_path = os.path.join(args.save_dir, f"{topic}-{today}-raw.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        ok(f"原始数据：{json_path}")

    # 同时把 md 写到 stdout（让 Claude/LLM 直接读取）
    print()
    print(md)
    return 0


def _build_topic(req: dict) -> str:
    parts = [req.get("city") or "", req.get("district") or "", req.get("area") or ""]
    parts = [p for p in parts if p]
    label = "调研" if req["intent"] == "research" else "租房"
    raw = "-".join(parts) + f"-{label}"
    # 文件名安全
    return re.sub(r'[\\/:*?"<>|]', "_", raw)


if __name__ == "__main__":
    sys.exit(main())
