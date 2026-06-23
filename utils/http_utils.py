#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 相关工具函数"""

import re
import time
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import httpx

_RE_STRIP_HTML = re.compile(r"<[^>]+>")

logger = logging.getLogger("news_monitor")

DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BACKOFF = 1.0
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


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


async def http_request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    retryable_status_codes: set[int] = RETRYABLE_STATUS_CODES,
    source_name: str = "",
    **kwargs
) -> httpx.Response:
    """带重试的 HTTP 请求

    Args:
        client: httpx 客户端
        method: HTTP 方法 (GET/POST)
        url: 请求 URL
        max_retries: 最大重试次数
        retry_backoff: 重试基础退避时间（秒），指数退避
        retryable_status_codes: 可重试的 HTTP 状态码
        source_name: 来源名称（用于日志）
        **kwargs: 传递给 httpx 请求的其他参数

    Returns:
        httpx.Response 对象

    Raises:
        最后一次请求的异常
    """
    last_exception: Optional[Exception] = None
    method_upper = method.upper()
    request_func = client.post if method_upper == "POST" else client.get

    for attempt in range(max_retries + 1):
        try:
            response = await request_func(url, **kwargs)
            if response.status_code < 400 or response.status_code not in retryable_status_codes:
                return response
            if attempt < max_retries:
                wait_time = retry_backoff * (2 ** attempt)
                src_info = f" [{source_name}]" if source_name else ""
                logger.warning(
                    f"HTTP {response.status_code}{src_info}，{wait_time:.1f}s 后第 {attempt + 1}/{max_retries} 次重试"
                )
                await asyncio.sleep(wait_time)
            else:
                return response
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout,
                httpx.RemoteProtocolError, httpx.NetworkError) as e:
            last_exception = e
            if attempt < max_retries:
                wait_time = retry_backoff * (2 ** attempt)
                src_info = f" [{source_name}]" if source_name else ""
                logger.warning(
                    f"请求失败{src_info}: {type(e).__name__}，{wait_time:.1f}s 后第 {attempt + 1}/{max_retries} 次重试"
                )
                await asyncio.sleep(wait_time)
            else:
                raise

    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry state")
