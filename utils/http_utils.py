#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 相关工具函数"""

import re
from contextlib import asynccontextmanager

_RE_STRIP_HTML = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    """去除 HTML 标签"""
    if not text:
        return ""
    return _RE_STRIP_HTML.sub("", text)


def clean_whitespace(text: str) -> str:
    """清理多余空白字符"""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


@asynccontextmanager
async def get_http_client(client, timeout=8.0, verify=True):
    """上下文管理器：有共享client则复用，否则创建并自动关闭"""
    import httpx
    if client is not None:
        yield client
    else:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=verify) as c:
            yield c


def build_user_agent(browser: str = "chrome") -> str:
    """构建常见的 User-Agent"""
    uas = {
        "chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "safari": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "mobile": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    }
    return uas.get(browser, uas["chrome"])
