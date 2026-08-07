#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML 解析器包共享辅助函数"""

import re
from finfeed.utils.time_utils import parse_relative_time

def _extract_time_from_parent(elem, max_levels: int = 5) -> str:
    """从元素向上查找父容器，提取时间文本"""
    container = elem
    for _ in range(max_levels):
        if container is None:
            break
        for t_elem in container.find_all(["p", "span", "div"], recursive=False):
            text = t_elem.get_text(strip=True)
            if text and len(text) < 30:
                ts = parse_relative_time(text)
                if ts > 0:
                    return text
        all_text = container.get_text(" ", strip=True)
        rel_m = re.search(r"(\d+\s*(?:分钟|小时|天)前)", all_text)
        if rel_m:
            return rel_m.group(1)
        time_m = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)", all_text)
        if time_m:
            return time_m.group(1)
        date_m = re.search(r"(\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2})", all_text)
        if date_m:
            return date_m.group(1)
        container = container.parent
    return ""

def _find_link_near_time(time_elem, max_levels: int = 5):
    """从时间元素向上查找包含它的链接元素"""
    container = time_elem
    for _ in range(max_levels):
        if container is None:
            break
        if container.name == "a" and container.get("href"):
            return container
        for link in container.find_all("a", href=True, recursive=False):
            return link
        container = container.parent
    return None
