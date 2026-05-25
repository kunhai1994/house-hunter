"""Jinja2 渲染器 — 把 engine 输出渲染成 Markdown 报告。"""

from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _common import find_skill_root  # type: ignore


def _template_dir() -> str:
    root = find_skill_root() or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(root, "scripts", "reports", "templates")


def render_search(payload: dict) -> str:
    """payload 必须包含：requirement, candidates, generated_*, poi_specs_by_cat, ...。"""
    return _render("search.md.j2", payload)


def render_deep_dive(payload: dict) -> str:
    return _render("deep_dive.md.j2", payload)


def _render(template_name: str, payload: dict) -> str:
    from jinja2 import Environment, FileSystemLoader, ChainableUndefined  # type: ignore

    env = Environment(
        loader=FileSystemLoader(_template_dir()),
        keep_trailing_newline=True,
        trim_blocks=False,
        lstrip_blocks=False,
        # ChainableUndefined: 允许 a.b.c 链式访问中的 None / 缺失字段（返回 Undefined）
        # 这样模板里的 {% if x.y.z %} 不会因为 x.y 不存在而报错
        undefined=ChainableUndefined,
    )

    # 默认时间字段
    now = dt.datetime.now()
    payload.setdefault("generated_at", now.isoformat(timespec="seconds"))
    payload.setdefault("generated_date", now.strftime("%Y-%m-%d"))
    payload.setdefault("generated_year", now.year)

    tmpl = env.get_template(template_name)
    return tmpl.render(**payload)
