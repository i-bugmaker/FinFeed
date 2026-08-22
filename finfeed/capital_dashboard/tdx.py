# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— TDX 连接管理。

封装 easy-tdx 的 MacClient：惰性连接、最佳主机自动选择、断线自动重连，
并对并发访问提供进程级单例与线程锁。
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from easy_tdx import MacClient
from easy_tdx.exceptions import TdxConnectionError

from . import config

logger = logging.getLogger("finfeed.capital_dashboard.tdx")

_lock = threading.RLock()  # 可重入：ensure_alive 与 get_client 存在嵌套调用
_client: Optional[MacClient] = None


def get_client() -> MacClient:
    """获取进程级 MacClient 单例（线程安全，断线自动重建）。

    首次调用执行全服务器延迟测速，选择最优主机。
    """
    global _client
    with _lock:
        if _client is None:
            logger.info(
                "连接 TDX 行情服务器 host=%s port=%s（自动测速）", config.TDX_HOST or "auto", config.TDX_PORT
            )
            _client = MacClient.from_best_host(
                hosts=[config.TDX_HOST] if config.TDX_HOST else None,
                port=config.TDX_PORT,
                timeout=config.TDX_TIMEOUT,
                auto_reconnect=True,
            )
            _client.connect()
        return _client


def ensure_alive() -> None:
    """校验连接存活，断线时重建（带锁防并发重建）。"""
    global _client
    with _lock:
        if _client is None:
            get_client()
            return
        try:
            _client.ensure_connected()
        except TdxConnectionError:
            logger.warning("TDX 连接异常，重建中…")
            try:
                _client.close()
            except Exception:  # noqa: BLE001
                pass
            _client = None
            get_client()


def close() -> None:
    """关闭全局连接（服务退出时调用）。"""
    global _client
    with _lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:  # noqa: BLE001
                pass
            _client = None
