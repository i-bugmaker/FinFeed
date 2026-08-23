# -*- coding: utf-8 -*-
"""全市场资金流与板块轮动监控大屏 —— 持久化层（SQLite 时序）。

补齐原模块「纯内存、重启即丢、无法盘后复盘/回测/跨日」的缺陷：

- 每轮把板块快照按时间写入 SQLite（默认 ``logs/capital_flow.db``），提供时序落盘；
- 进程启动时可从落盘数据回填 ``SnapshotStore`` 的 ``current`` 与 ``history``，
  重启后大屏立即可见上一交易时段的最后状态，轮动分析也有历史可比对；
- 所有写操作均 try/except 兜底，数据库不可用（如只读文件系统）时静默降级，
  绝不影响资金流主链路（采集/分析/推送）。

仅依赖标准库 ``sqlite3``，无需额外依赖。
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading

from .models import BoardFlow, MarketSnapshot

logger = logging.getLogger("finfeed.capital_dashboard.persist")

DB_PATH = os.environ.get("CAPITAL_DB", "logs/capital_flow.db")
_lock = threading.RLock()


def _conn() -> sqlite3.Connection:
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS board_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, ts_label TEXT,
            code TEXT, name TEXT, board_type TEXT,
            change_pct REAL, amount REAL, main_net REAL,
            up_count INTEGER, down_count INTEGER, member_count INTEGER
        )"""
    )
    return conn


def save_boards(snapshot: MarketSnapshot) -> None:
    """将一轮的板块快照追加写入时序表（best-effort）。"""
    if not snapshot.boards:
        return
    try:
        with _lock:
            conn = _conn()
            try:
                rows = [
                    (
                        snapshot.ts, snapshot.ts_label,
                        b.code, b.name, b.board_type,
                        b.change_pct, b.amount, b.main_net,
                        b.up_count, b.down_count, b.member_count,
                    )
                    for b in snapshot.boards
                ]
                conn.executemany(
                    "INSERT INTO board_snapshots "
                    "(ts, ts_label, code, name, board_type, change_pct, amount, main_net, "
                    "up_count, down_count, member_count) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                conn.commit()
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("资金流板块快照持久化失败（已降级）: %s", exc)


def load_recent_snapshots(limit: int = 120) -> list[MarketSnapshot]:
    """读取最近的若干轮板块快照，按 ts 重组为 ``MarketSnapshot`` 列表（用于启动回填）。"""
    try:
        with _lock:
            conn = _conn()
            try:
                cur = conn.execute(
                    "SELECT ts, ts_label, code, name, board_type, change_pct, amount, "
                    "main_net, up_count, down_count, member_count "
                    "FROM board_snapshots ORDER BY id DESC LIMIT ?",
                    (limit * 80,),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("资金流快照读取失败（已降级）: %s", exc)
        return []

    # 按 ts 分组
    groups: dict[str, dict] = {}
    for r in rows:
        ts, ts_label, code, name, bt, chg, amt, mn, up, dn, mc = r
        g = groups.setdefault(ts, {"ts": ts, "ts_label": ts_label, "boards": []})
        g["boards"].append(
            BoardFlow(
                code=code, name=name, board_type=bt, change_pct=chg,
                amount=amt, main_net=mn, up_count=up, down_count=dn, member_count=mc,
            )
        )
    snaps = [
        MarketSnapshot(ts=g["ts"], ts_label=g["ts_label"], boards=g["boards"])
        for g in groups.values()
    ]
    snaps.sort(key=lambda s: s.ts)
    return snaps[-limit:]


def prune(keep: int = 20000) -> None:
    """清理过量历史行（保留最近 keep 行），避免数据库无限增长。"""
    try:
        with _lock:
            conn = _conn()
            try:
                conn.execute(
                    "DELETE FROM board_snapshots WHERE id NOT IN "
                    "(SELECT id FROM board_snapshots ORDER BY id DESC LIMIT ?)",
                    (keep,),
                )
                conn.commit()
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("资金流快照清理失败（已忽略）: %s", exc)
