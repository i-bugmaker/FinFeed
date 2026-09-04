"""统一 SQLite 连接出口。

全仓所有 sqlite3.connect 必须经由本模块（架构评估 §4：此前存在 5 条独立
连接路径，各自 PRAGMA 配置不一致，llm/cleanup.py 甚至硬编码相对路径导致
CWD 敏感）。

统一行为：
  * 确保父目录存在
  * busy_timeout / WAL / cache / mmap / temp_store / UTF-8 / foreign_keys
  * row_factory 默认 sqlite3.Row（可传 None 退回裸 tuple）

用法：
    from finfeed.storage.connect import connect
    conn = connect("logs/xxx.db")          # Row 行工厂 + 全套 PRAGMA
    conn = connect(p, row_factory=None)    # 裸 tuple（按需）
"""
from __future__ import annotations

import os
import sqlite3
from typing import Optional, Union

from finfeed.config.settings import USE_WAL_MODE

RowFactory = Optional[Union[object]]


def connect(
    path: str,
    *,
    row_factory: RowFactory = sqlite3.Row,
    timeout: float = 15.0,
    wal: Optional[bool] = None,
    check_same_thread: bool = False,
) -> sqlite3.Connection:
    """创建带统一 PRAGMA 配置的 SQLite 连接。

    Args:
        path: 数据库文件路径（相对路径按调用进程 CWD 解析，推荐传绝对路径）
        row_factory: 默认 sqlite3.Row；传 None 则返回裸 tuple
        timeout: sqlite3.connect 的锁等待秒数
        wal: 覆盖全局 USE_WAL_MODE；None 表示跟随全局配置
        check_same_thread: 默认 False（项目内跨线程共享场景多）
    """
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(path, check_same_thread=check_same_thread, timeout=timeout)
    if row_factory is not None:
        conn.row_factory = row_factory
    conn.text_factory = str
    if (USE_WAL_MODE if wal is None else wal):
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA encoding='UTF-8'")
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn
