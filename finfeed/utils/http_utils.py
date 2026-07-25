#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 相关工具函数"""

import re

_RE_STRIP_HTML = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """去除 HTML 标签"""
    if not text:
        return ""
    return _RE_STRIP_HTML.sub("", text)
