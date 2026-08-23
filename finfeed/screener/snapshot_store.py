#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行情快照持久化（历史数据积累）。

背景：回测最大盲区是「资金面 / 估值因子无历史数据可验证」（东财 datacenter
只存最新一期）。本模块把每次 fetch_snapshot 的规范列快照按交易日落库，
积累足够历史后（≥60 个交易日），回测可切换到「真实资金/估值因子」路径，
消除当前回测仅动量/质量有效的结构性缺口。

存储：SQLite `logs/screener_snapshots.db`，按 (trade_date, code) 主键去重；
单日 5000+ 行 × 20 列，单日约 1~2MB，一年约 300MB，可接受。
写入采用后台线程批量提交，不阻塞主流程。
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pandas as pd

from .contract import REQUIRED_COLS

logger = logging.getLogger("finfeed.screener.snapshot_store")

_SNAP_DB = Path(__file__).resolve().parent.parent.parent / "logs" / "screener_snapshots.db"

# 落库列（规范列 + 行业/市值/情绪等中性化与评分所需）
_STORE_COLS = REQUIRED_COLS + ["name", "industry", "industry_sub", "circ_cap",
                               "main_net_5d_pct", "chg_today", "amplitude"]


class SnapshotStore:
    """按交易日持久化全市场快照。"""

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = str(db_path or _SNAP_DB)
        self._lock = threading.Lock()
        self._init()

    def _init(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            conn = sqlite3.connect(self._path, timeout=10)
            try:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS snapshots (
                        trade_date TEXT NOT NULL,
                        code TEXT NOT NULL,
                        market INTEGER,
                        name TEXT,
                        industry TEXT,
                        industry_sub TEXT,
                        close REAL, pre_close REAL, open REAL, high REAL, low REAL,
                        vol REAL, vol_ratio REAL, amount REAL,
                        total_shares REAL, float_shares REAL, eps REAL,
                        total_market_cap REAL, dividend_yield REAL, turnover REAL,
                        circulating_capital_z REAL, pe_ttm REAL,
                        main_net_amount REAL, main_net_ratio REAL, main_net_5d_amount REAL,
                        change_5d_pct REAL, change_10d_pct REAL, change_20d_pct REAL,
                        change_60d_pct REAL, change_1y_pct REAL,
                        annual_limit_up_days REAL, consecutive_up_days REAL,
                        ddx REAL, vol_speed_pct REAL,
                        circ_cap REAL, main_net_5d_pct REAL, chg_today REAL, amplitude REAL,
                        saved_at TEXT,
                        PRIMARY KEY (trade_date, code)
                    )"""
                )
                # 幂等迁移：旧表补情绪字段列（忽略已存在）
                for _col, _ddl in (("annual_limit_up_days", "REAL"), ("consecutive_up_days", "REAL"),
                                   ("ddx", "REAL"), ("vol_speed_pct", "REAL")):
                    try:
                        conn.execute(f"ALTER TABLE snapshots ADD COLUMN {_col} {_ddl}")
                    except sqlite3.OperationalError:
                        pass  # 列已存在
                conn.commit()
            finally:
                conn.close()

    def save_snapshot(self, df: pd.DataFrame, trade_date: str) -> int:
        """保存一日快照（INSERT OR REPLACE 去重），返回写入行数。

        在调用线程内同步执行（fetch_snapshot 低频，单日 5000 行耗时 <1s）。
        """
        if df is None or len(df) == 0 or not trade_date:
            return 0
        rows: list[tuple] = []
        for rec in df.to_dict("records"):
            rows.append(self._row_to_tuple(rec, trade_date))
        if not rows:
            return 0
        try:
            with self._lock:
                conn = sqlite3.connect(self._path, timeout=30)
                try:
                    conn.executemany(
                        """INSERT OR REPLACE INTO snapshots VALUES
                           (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        rows,
                    )
                    conn.commit()
                finally:
                    conn.close()
            return len(rows)
        except sqlite3.Error as exc:
            logger.warning("快照落库失败（%s）: %s", trade_date, exc)
            return 0

    def available_dates(self) -> list[str]:
        """已积累的交易日列表（升序）。"""
        try:
            conn = sqlite3.connect(self._path, timeout=10)
            try:
                rows = conn.execute("SELECT DISTINCT trade_date FROM snapshots ORDER BY trade_date").fetchall()
                return [r[0] for r in rows]
            finally:
                conn.close()
        except sqlite3.Error:
            return []

    def load_date(self, trade_date: str) -> pd.DataFrame | None:
        """读取指定交易日快照（规范列 DataFrame），无数据返回 None。"""
        try:
            conn = sqlite3.connect(self._path, timeout=10)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT * FROM snapshots WHERE trade_date=?", (trade_date,)
                ).fetchall()
            finally:
                conn.close()
            if not rows:
                return None
            df = pd.DataFrame([dict(r) for r in rows])
            return df
        except sqlite3.Error:
            return None

    @staticmethod
    def _row_to_tuple(rec: dict, trade_date: str) -> tuple:
        return (
            trade_date,
            str(rec.get("code", "") or ""),
            int(rec.get("market", 0) or 0) if rec.get("market") is not None else None,
            str(rec.get("name", "") or ""),
            str(rec.get("industry", "") or ""),
            str(rec.get("industry_sub", "") or ""),
            *[rec.get(c) for c in (
                "close", "pre_close", "open", "high", "low",
                "vol", "vol_ratio", "amount", "total_shares", "float_shares", "eps",
                "total_market_cap", "dividend_yield", "turnover",
                "circulating_capital_z", "pe_ttm",
                "main_net_amount", "main_net_ratio", "main_net_5d_amount",
                "change_5d_pct", "change_10d_pct", "change_20d_pct",
                "change_60d_pct", "change_1y_pct",
                "annual_limit_up_days", "consecutive_up_days", "ddx", "vol_speed_pct",
                "circ_cap", "main_net_5d_pct", "chg_today", "amplitude",
            )],
            "",
        )


snapshot_store = SnapshotStore()
