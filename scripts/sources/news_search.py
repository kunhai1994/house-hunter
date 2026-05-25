"""新闻搜索 — 通过 Bing/百度搜索引擎做多关键词检索。

由于 Claude Code 内置的 WebSearch 是 LLM 工具（不是 Python 可调用），
这里用 Bing 网页搜索 + 简单 HTML 解析做兜底。

主要用于安全事件检索（搭配 sources/xhs.py 的小红书检索做交叉验证）。
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import http_get, cached, parallel_map, RateLimiter  # type: ignore


_rate = RateLimiter(min_interval_s=1.5)


SEARCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


@cached("bing_search", ttl_seconds=21600)
def bing_search(query: str, count: int = 10) -> list[dict]:
    """Bing 搜索结果。返回 [{"title", "url", "snippet"}]。"""
    _rate.wait("bing")
    url = f"https://cn.bing.com/search?q={urllib.parse.quote(query)}&count={count}"
    html = http_get(url, timeout=12, headers=SEARCH_HEADERS)
    if not html:
        return []
    return _parse_bing(html)[:count]


def _parse_bing(html: str) -> list[dict]:
    out = []
    # Bing 结果块：<li class="b_algo">...<h2><a href="URL">TITLE</a></h2>...<div class="b_caption"><p>SNIPPET</p>
    blocks = re.findall(r'<li class="b_algo">(.*?)</li>', html, re.DOTALL)
    for b in blocks:
        title_m = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, re.DOTALL)
        snippet_m = re.search(r'<p[^>]*>(.*?)</p>', b, re.DOTALL)
        if not title_m:
            continue
        title = re.sub(r'<[^>]+>', '', title_m.group(2)).strip()
        url = title_m.group(1)
        snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip() if snippet_m else ""
        out.append({"title": title, "url": url, "snippet": snippet})
    return out


@cached("baidu_news_search", ttl_seconds=21600)
def baidu_search(query: str, count: int = 10) -> list[dict]:
    """百度搜索回退。"""
    _rate.wait("baidu_search")
    url = f"https://www.baidu.com/s?wd={urllib.parse.quote(query)}&rn={count}"
    html = http_get(url, timeout=12, headers=SEARCH_HEADERS)
    if not html:
        return []
    return _parse_baidu(html)[:count]


def _parse_baidu(html: str) -> list[dict]:
    out = []
    blocks = re.findall(r'<div class="result[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.DOTALL)
    for b in blocks:
        title_m = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, re.DOTALL)
        if not title_m:
            continue
        title = re.sub(r'<[^>]+>', '', title_m.group(2)).strip()
        url = title_m.group(1)
        if not title:
            continue
        out.append({"title": title, "url": url, "snippet": ""})
    return out


# ---------------------------------------------------------------------------
# 高层 API
# ---------------------------------------------------------------------------
def safety_incidents(community: str, city: str = "",
                     keywords: list[str] | None = None) -> list[dict]:
    """安全事件检索：返回去重后的 [{"title","url","snippet","keyword","engine"}]。"""
    if keywords is None:
        keywords = ["凶案", "命案", "跳楼", "火灾", "入室盗窃", "纠纷"]
    queries = [f"{city} {community} {kw}".strip() for kw in keywords]
    results = parallel_map(lambda q: bing_search(q, 8), queries, max_workers=4)

    seen: dict[str, dict] = {}
    for query, batch in zip(queries, results):
        kw = query.split()[-1] if query else ""
        for r in (batch or []):
            url = r.get("url")
            if not url or url in seen:
                continue
            r2 = dict(r)
            r2["keyword"] = kw
            r2["engine"] = "bing"
            seen[url] = r2
    return list(seen.values())


def health() -> bool:
    return bool(bing_search("test", 3))
