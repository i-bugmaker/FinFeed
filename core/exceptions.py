#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一异常处理模块

定义项目专用异常类和错误处理工具。
"""

import logging
import traceback
from typing import Optional, Callable, Any

logger = logging.getLogger("news_monitor")


class FinFeedError(Exception):
    """FinFeed 基础异常"""
    pass


class FetchError(FinFeedError):
    """抓取异常"""

    def __init__(self, source_name: str, message: str, cause: Optional[Exception] = None):
        super().__init__(f"{source_name}: {message}")
        self.source_name = source_name
        self.message = message
        self.cause = cause


class ParseError(FinFeedError):
    """解析异常"""

    def __init__(self, source_name: str, message: str, cause: Optional[Exception] = None):
        super().__init__(f"{source_name}: {message}")
        self.source_name = source_name
        self.message = message
        self.cause = cause


class StorageError(FinFeedError):
    """存储异常"""

    def __init__(self, message: str, cause: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.cause = cause


class ConfigurationError(FinFeedError):
    """配置异常"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class RateLimitError(FetchError):
    """速率限制异常"""

    def __init__(self, source_name: str, retry_after: int = 60):
        super().__init__(source_name, f"速率限制，建议等待 {retry_after} 秒")
        self.retry_after = retry_after


class CircuitOpenError(FetchError):
    """断路器打开异常"""

    def __init__(self, source_name: str, remaining: int):
        super().__init__(source_name, f"断路器打开，剩余冷却时间 {remaining} 秒")
        self.remaining = remaining


def log_error(
    source_name: str,
    message: str,
    exc: Optional[Exception] = None,
    level: int = logging.WARNING,
) -> None:
    """记录错误日志

    Args:
        source_name: 源名称
        message: 错误消息
        exc: 原始异常
        level: 日志级别
    """
    if exc:
        logger.log(level, f"{source_name}: {message}", exc_info=True)
    else:
        logger.log(level, f"{source_name}: {message}")


def log_exception(
    source_name: str,
    exc: Exception,
    context: str = "",
) -> None:
    """记录异常详细信息

    Args:
        source_name: 源名称
        exc: 异常
        context: 上下文描述
    """
    tb_str = traceback.format_exc()
    logger.error(f"{source_name}: {context} - {str(exc)}\n{tb_str}")


def safe_execute(
    func: Callable,
    *args,
    error_message: str = "操作失败",
    default: Any = None,
    log_level: int = logging.WARNING,
    **kwargs,
) -> Any:
    """安全执行函数，捕获异常并返回默认值

    Args:
        func: 要执行的函数
        error_message: 错误消息
        default: 默认返回值
        log_level: 日志级别
        *args: 函数参数
        **kwargs: 函数关键字参数

    Returns:
        函数执行结果或默认值
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.log(log_level, f"{error_message}: {str(e)}")
        return default


async def safe_execute_async(
    func: Callable,
    *args,
    error_message: str = "异步操作失败",
    default: Any = None,
    log_level: int = logging.WARNING,
    **kwargs,
) -> Any:
    """安全执行异步函数，捕获异常并返回默认值

    Args:
        func: 要执行的异步函数
        error_message: 错误消息
        default: 默认返回值
        log_level: 日志级别
        *args: 函数参数
        **kwargs: 函数关键字参数

    Returns:
        函数执行结果或默认值
    """
    try:
        return await func(*args, **kwargs)
    except Exception as e:
        logger.log(log_level, f"{error_message}: {str(e)}")
        return default


def handle_http_error(
    source_name: str,
    status_code: int,
    retry_after_header: Optional[str] = None,
) -> Optional[RateLimitError]:
    """处理HTTP错误状态码

    Args:
        source_name: 源名称
        status_code: HTTP状态码
        retry_after_header: Retry-After 响应头

    Returns:
        RateLimitError 如果是429，否则抛出 FetchError
    """
    if status_code == 429:
        retry_after = int(retry_after_header) if retry_after_header and retry_after_header.isdigit() else 60
        return RateLimitError(source_name, retry_after)

    raise FetchError(source_name, f"HTTP {status_code}")