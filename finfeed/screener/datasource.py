#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股模块数据源层：多源接入 + 回退链 + 缺失语义 + K 线缓存。

职责：
- **主数据源** easy-tdx（MacClient）拉取全 A 股实时行情/基本面快照；
- **回退数据源** 东方财富 datacenter 全市场快照（`finfeed.market.snapshot`，日频定格，
  仅在主源失败/异常时启用），回退链显式记录在 SnapshotBundle；
- **缺失语义**：列缺失一律置 NaN（绝不补 0 冒充），评分层按缺失三态处理，
  避免「数据缺失」被误判为「停牌/亏损」；
- **K 线技术面**：指标本地 SQLite 缓存（按交易日复用），二次运行零重复请求；
- **快照时间真实化**：easy-tdx 服务器时间（SERVER_UPDATE_DATE/TIME）优先，
  东财回退用交易日期，均非本地时钟冒充。

复用项目既有 TDX 连接单例（finfeed.capital_dashboard.tdx）。
"""

from __future__ import annotations

import asyncio
import logging
import math
import queue
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from easy_tdx import Adjust, Category, MacClient, Period, SortOrder, SortType
from easy_tdx.codec.bitmap import FieldBit, PresetField

from finfeed.capital_dashboard import config as tdx_config
from finfeed.capital_dashboard.tdx import call_lock, ensure_alive, get_client
from finfeed.capital_dashboard.tdx import close as close_tdx
from finfeed.utils.time_utils import now_bj

from .contract import (
    SnapshotBundle,
    build_missing_mask,
    coverage_ratio,
    normalize_frame,
    validate_snapshot,
)

logger = logging.getLogger("finfeed.screener.datasource")

# 批量报价请求字段：基础 OHLC + 量额 + 估值 + 资金流 + 动量 + 股本 + 行业 + 服务器时间
SCREENER_FIELDS = (
    PresetField.BASIC
    + PresetField.VOLUME
    + FieldBit.AMOUNT
    + FieldBit.TURNOVER
    + FieldBit.PE_TTM
    + FieldBit.MAIN_NET_AMOUNT
    + FieldBit.MAIN_NET_RATIO
    + FieldBit.MAIN_NET_5D_AMOUNT
    + FieldBit.FLOAT_SHARES
    + FieldBit.TOTAL_SHARES
    + FieldBit.EPS
    + FieldBit.DIVIDEND_YIELD
    + FieldBit.CHANGE_5D_PCT
    + FieldBit.CHANGE_10D_PCT
    + FieldBit.CHANGE_20D_PCT
    + FieldBit.CHANGE_60D_PCT
    + FieldBit.CHANGE_1Y_PCT
    + FieldBit.CIRCULATING_CAPITAL_Z
    + FieldBit.TOTAL_MARKET_CAP_AB
    + FieldBit.VOL_RATIO
    + FieldBit.INDUSTRY
    + FieldBit.INDUSTRY_SUB
    + FieldBit.ANNUAL_LIMIT_UP_DAYS    # 年内涨停天数（情绪/事件：涨停基因）
    + FieldBit.CONSECUTIVE_UP_DAYS     # 连涨天数（短线动能）
    + FieldBit.DDX                     # 大单动向（大单净量比）
    + FieldBit.VOL_SPEED_PCT           # 量速（放量强度）
    + FieldBit.SERVER_UPDATE_DATE
    + FieldBit.SERVER_UPDATE_TIME
)

# 列名归一化（easy-tdx 返回列 -> 规范列）
_COL_RENAME = {
    "total_market_cap_ab": "total_market_cap",
}


class DataSourceError(RuntimeError):
    """所有数据源均不可用（调用方应明确报错，禁止降级到伪造数据）。"""


# ---------------------------------------------------------------------------
# 快照获取：主源 easy-tdx → 回退东财 datacenter
# ---------------------------------------------------------------------------

def _persist_snapshot(bundle: SnapshotBundle) -> None:
    """把快照按交易日落库（历史数据积累，供未来资金/估值因子回测）。失败不阻断主流程。"""
    try:
        from finfeed.utils.time_utils import now_bj

        from .snapshot_store import snapshot_store

        as_of = bundle.as_of or ""
        # 支持两种格式：YYYYMMDD HH:MM:SS（easy-tdx）与 YYYY-MM-DD HH:MM:SS（东财回退）
        date_part = as_of[:10]
        if len(date_part) >= 8 and date_part[:8].isdigit():
            date_part = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
        if len(date_part) != 10 or date_part[4] != "-":
            date_part = now_bj().strftime("%Y-%m-%d")
        n = snapshot_store.save_snapshot(bundle.df, date_part)
        logger.debug("快照已持久化 %s：%d 行", date_part, n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("快照持久化失败（不影响本次评分）: %s", exc)


def fetch_snapshot(count: int = 12000) -> SnapshotBundle:
    """获取全市场行情快照（带回退链），返回统一 SnapshotBundle。

    回退链：easy-tdx（实时）→ 东财 datacenter（日频定格）→ 明确失败。
    数据源健康度记录到 core/health（screener.easy-tdx / screener.eastmoney）。
    """
    from finfeed.core.health import get_health_monitor

    hm = get_health_monitor()

    # 1) 主源：easy-tdx 实时
    t0 = time.monotonic()
    try:
        raw, as_of, kind = _fetch_tdx(count)
        df = normalize_frame(raw, "easy-tdx")
        problems = validate_snapshot(df, "easy-tdx")
        if problems:
            logger.warning("easy-tdx 快照未通过健康校验：%s", problems)
            raise DataSourceError("; ".join(problems))
        hm.record_success("screener.easy-tdx", time.monotonic() - t0)
        bundle = _make_bundle(df, "easy-tdx", ["easy-tdx"], as_of, kind)
        _persist_snapshot(bundle)
        return bundle
    except DataSourceError:
        hm.record_failure("screener.easy-tdx", "健康校验未通过")
        raise
    except Exception as exc:  # noqa: BLE001
        hm.record_failure("screener.easy-tdx", str(exc)[:200])
        logger.warning("easy-tdx 主源不可用（%s），尝试东财回退…", exc)

    # 2) 回退源：东财 datacenter 全市场快照（日频定格）
    t0 = time.monotonic()
    try:
        raw, as_of = _fetch_eastmoney()
        df = normalize_frame(raw, "eastmoney")
        problems = validate_snapshot(df, "eastmoney")
        if problems:
            logger.warning("东财回退快照未通过健康校验：%s", problems)
            raise DataSourceError("; ".join(problems))
        hm.record_success("screener.eastmoney", time.monotonic() - t0)
        bundle = _make_bundle(df, "eastmoney", ["easy-tdx", "eastmoney"], as_of, "trade_date")
        _persist_snapshot(bundle)
        logger.info("已回退到东财 datacenter 快照（%d 行，as_of=%s）", len(df), as_of)
        return bundle
    except Exception as exc:  # noqa: BLE001
        hm.record_failure("screener.eastmoney", str(exc)[:200])
        logger.exception("东财回退源亦不可用")
        raise DataSourceError(
            "行情数据源全部不可用：easy-tdx（实时）与东财 datacenter（日频）均失败，"
            f"最后错误：{exc}。系统不会使用伪造/占位数据，请检查网络与数据源状态。"
        ) from exc


def _make_bundle(df: pd.DataFrame, source: str, chain: list[str],
                 as_of: str, kind: str) -> SnapshotBundle:
    """由规范列 DataFrame 组装 SnapshotBundle（含派生字段与缺失掩码）。"""
    df = _add_derived(df)
    mask = build_missing_mask(df)
    return SnapshotBundle(
        df=df,
        as_of=as_of,
        as_of_kind=kind,
        source=source,
        fallback_chain=chain,
        coverage=coverage_ratio(mask),
        missing_mask=mask,
    )


def _fetch_tdx(count: int = 12000) -> tuple[pd.DataFrame, str, str]:
    """easy-tdx 实时快照。返回 (原始 df, as_of, as_of_kind)。"""
    ensure_alive()
    client = get_client()
    df = client.get_stock_quotes_list(
        Category.A,
        count=count,
        sort_type=SortType.CODE,
        sort_order=SortOrder.ASC,
        fields=SCREENER_FIELDS,
    )
    if df is None or len(df) == 0:
        raise RuntimeError("easy-tdx 返回空行情，可能网络异常")

    df = df.rename(columns=_COL_RENAME)
    # 服务器时间：优先取 SERVER_UPDATE_DATE/TIME 众数，缺失则回退本地时间
    as_of, kind = _extract_server_time(df)
    return df, as_of, kind


def _extract_server_time(df: pd.DataFrame) -> tuple[str, str]:
    """从快照提取服务器时间。返回 (as_of, kind)。"""
    date_col = next((c for c in df.columns if str(c).lower() == "server_update_date"), None)
    time_col = next((c for c in df.columns if str(c).lower() == "server_update_time"), None)
    date_v = time_v = None
    if date_col is not None:
        vals = df[date_col].dropna().astype(str)
        if len(vals):
            date_v = vals.mode().iloc[0] if not vals.mode().empty else vals.iloc[0]
    if time_col is not None:
        vals = df[time_col].dropna().astype(str)
        if len(vals):
            time_v = vals.mode().iloc[0] if not vals.mode().empty else vals.iloc[0]
    if date_v:
        t = str(time_v).zfill(6) if time_v else "000000"
        try:
            return f"{date_v} {t[:2]}:{t[2:4]}:{t[4:6]}", "realtime"
        except Exception:  # noqa: BLE001
            pass
    return now_bj().strftime("%Y-%m-%d %H:%M:%S"), "local"


def _fetch_eastmoney() -> tuple[pd.DataFrame, str]:
    """东财 datacenter 全市场快照（回退源，日频定格）。

    复用 finfeed.market.snapshot.fetch_market_snapshot（约 4 秒拉全 5000+ 只）。
    注意：在无事件循环的线程/CLI 中调用（asyncio.run）；FastAPI 异步上下文
    中不会走到此路径（主源正常时不需要回退）。
    """
    from finfeed.market.snapshot import fetch_market_snapshot

    rows, snapshot_date = asyncio.run(fetch_market_snapshot())
    if not rows or snapshot_date == "":
        raise RuntimeError("东财 datacenter 快照返回空")
    df = _eastmoney_to_frame(rows)
    as_of = f"{snapshot_date} 15:00:00" if snapshot_date else ""
    return df, as_of


def _eastmoney_to_frame(rows: list[dict]) -> pd.DataFrame:
    """东财快照行 → 规范列 DataFrame（缺失字段置 NaN）。

    东财报表字段契约（finfeed/market/snapshot.py 实测）：
        code/name/close_price/pct_chg/turnover/main_net/main_ratio。
    其余规范列（PE/EPS/动量/股本等）该源不提供 → NaN（评分层按缺失处理）。
    """
    out: list[dict] = []
    for r in rows:
        code = str(r.get("code", "") or "").strip()
        if not code:
            continue
        close = _f(r.get("close_price"))
        pct = _f(r.get("pct_chg"))
        pre_close = close / (1.0 + pct / 100.0) if close > 0 and abs(pct) < 100 else float("nan")
        out.append({
            "market": _market_of_code(code),
            "code": code,
            "name": str(r.get("name", "") or ""),
            "pre_close": pre_close,
            "open": float("nan"),
            "high": float("nan"),
            "low": float("nan"),
            "close": close,
            "vol": float("nan"),
            "vol_ratio": float("nan"),
            "amount": float("nan"),
            "total_shares": float("nan"),
            "float_shares": float("nan"),
            "eps": float("nan"),
            "total_market_cap": float("nan"),
            "dividend_yield": float("nan"),
            "turnover": _f(r.get("turnover")),
            "circulating_capital_z": float("nan"),
            "pe_ttm": float("nan"),
            "main_net_amount": _f(r.get("main_net")),
            "main_net_ratio": _f(r.get("main_ratio")),
            "main_net_5d_amount": float("nan"),
            "change_5d_pct": float("nan"),
            "change_10d_pct": float("nan"),
            "change_20d_pct": float("nan"),
            "change_60d_pct": float("nan"),
            "change_1y_pct": float("nan"),
            # 情绪/事件字段：东财回退源不提供 → NaN（缺失语义）
            "annual_limit_up_days": float("nan"),
            "consecutive_up_days": float("nan"),
            "ddx": float("nan"),
            "vol_speed_pct": float("nan"),
        })
    return pd.DataFrame(out)


def _market_of_code(code: str) -> int:
    """由 6 位代码推导通达信市场字段：1=沪 0=深 2=北。"""
    if code.startswith(("60", "68", "90")):
        return 1
    if code.startswith(("00", "30", "20")):
        return 0
    if code.startswith(("8", "4", "92")):
        return 2
    return 0


def _add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """计算派生字段：当日涨跌幅、振幅、流通市值、5日主力净流入占流通比。

    缺失语义：pre_close/close 缺失时派生字段保持 NaN（绝不用 0 冒充"平盘"）。
    内部 copy，避免修改调用方数据（切片副本赋值会触发 SettingWithCopyWarning）。
    """
    df = df.copy()
    close = pd.to_numeric(df["close"], errors="coerce")
    pre = pd.to_numeric(df["pre_close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    fs = pd.to_numeric(df["float_shares"], errors="coerce")

    valid = pre > 0
    df["chg_today"] = np.where(valid, (close - pre) / pre * 100.0, float("nan"))
    df["amplitude"] = np.where(valid, (high - low) / pre * 100.0, float("nan"))
    circ = fs * 1e4 * close
    df["circ_cap"] = circ
    net5 = pd.to_numeric(df["main_net_5d_amount"], errors="coerce")
    df["main_net_5d_pct"] = np.where(circ > 0, net5 / circ * 100.0, float("nan"))
    return df


# ---------------------------------------------------------------------------
# 技术面：K 线指标 + SQLite 缓存（按交易日复用）
# ---------------------------------------------------------------------------

_CACHE_DB = Path(__file__).resolve().parent.parent.parent / "logs" / "screener_cache.db"


class KLineCache:
    """K 线技术指标缓存（SQLite，按 (code, trade_date) 键）。

    目的：富化只对 TopN 抓取、成本高（每只一次网络请求），跨运行复用
    当日指标可把二次运行的技术面耗时从数十秒降到接近 0。
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._path = str(db_path or _CACHE_DB)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialized = False

    def _conn(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        self._path and Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        with self._init_lock:
            if not self._initialized:
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS kline_metrics (
                        code TEXT NOT NULL,
                        trade_date TEXT NOT NULL,
                        realized_vol_ann REAL,
                        ma_align INTEGER,
                        drawdown_from_high REAL,
                        updated_at TEXT,
                        PRIMARY KEY (code, trade_date)
                    )"""
                )
                conn.commit()
                self._initialized = True
        self._local.conn = conn
        return conn

    def get(self, code: str, trade_date: str) -> dict[str, Any] | None:
        try:
            cur = self._conn().execute(
                "SELECT realized_vol_ann, ma_align, drawdown_from_high FROM kline_metrics "
                "WHERE code=? AND trade_date=?",
                (code, trade_date),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "realized_vol_ann": row[0],
                "ma_align": bool(row[1]),
                "drawdown_from_high": row[2],
            }
        except sqlite3.Error:
            return None

    def put(self, code: str, trade_date: str, metrics: dict[str, Any]) -> None:
        try:
            self._conn().execute(
                "INSERT OR REPLACE INTO kline_metrics "
                "(code, trade_date, realized_vol_ann, ma_align, drawdown_from_high, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (code, trade_date,
                 metrics.get("realized_vol_ann"),
                 1 if metrics.get("ma_align") else 0,
                 metrics.get("drawdown_from_high"),
                 now_bj().strftime("%Y-%m-%d %H:%M:%S")),
            )
            self._conn().commit()
        except sqlite3.Error:
            pass

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._local.conn = None


_kline_cache = KLineCache()


def _kline_metrics_from(client: MacClient, market: int, code: str, kline_count: int) -> dict[str, Any]:
    """用指定 TDX 客户端取日线 K 线，计算技术面指标（失败返回空指标）。"""
    df = client.get_stock_kline(
        market, code, Period.DAILY, count=kline_count, adjust=Adjust.QFQ
    )
    if df is None or len(df) < 2:
        return {"realized_vol_ann": None, "ma_align": False, "drawdown_from_high": None}

    cols = {str(c).lower(): c for c in df.columns}
    close = df[cols.get("close", "close")].astype(float)
    high = df[cols.get("high", "high")].astype(float)
    if len(close) < 2:
        return {"realized_vol_ann": None, "ma_align": False, "drawdown_from_high": None}

    rets = close.pct_change().dropna()
    realized_vol_ann = None
    if len(rets) >= 5:
        std = float(rets.std())
        if math.isfinite(std):
            realized_vol_ann = std * math.sqrt(242.0) * 100.0

    ma_align = False
    if len(close) >= 60:
        ma20 = float(close.tail(20).mean())
        ma60 = float(close.tail(60).mean())
        ma_align = bool(close.iloc[-1] > ma20 > ma60)

    drawdown_from_high = None
    if len(high) >= 20:
        peak = float(high.max())
        if peak > 0:
            drawdown_from_high = (float(close.iloc[-1]) - peak) / peak * 100.0

    return {
        "realized_vol_ann": realized_vol_ann,
        "ma_align": ma_align,
        "drawdown_from_high": drawdown_from_high,
    }


def _kline_metrics(market: int, code: str, kline_count: int) -> dict[str, Any]:
    """全局单例路径取 K 线指标（回退用；受全局调用锁串行化）。"""
    client = get_client()
    return _kline_metrics_from(client, market, code, kline_count)


# 建连互斥锁：easy-tdx 首次建连写 ~/.easy_tdx/config.json，
# 并发建连存在文件竞争（实测 WinError 32），所有建连必须串行。
_CONNECT_LOCK = threading.Lock()


class _KlinePool:
    """K 线抓取连接池（每线程独占连接，并发安全）。

    设计：
    - 顺序预建 max_workers 条 MacClient（避免 config.json 文件竞争）；
    - 借出连接执行请求（easy-tdx 客户端非线程安全，但每连接同一时刻仅一个线程使用）；
    - 连接异常时失效重建；整体不可用时回退全局单例（串行）。
    """

    def __init__(self, size: int = 3) -> None:
        self._size = max(1, min(size, 5))
        self._pool: queue.Queue = queue.Queue()
        self._ready = False

    def _init(self) -> None:
        if self._ready:
            return
        with _CONNECT_LOCK:
            if self._ready:
                return
            for _ in range(self._size):
                try:
                    c = MacClient.from_best_host(
                        hosts=[tdx_config.TDX_HOST] if tdx_config.TDX_HOST else None,
                        port=tdx_config.TDX_PORT,
                        timeout=tdx_config.TDX_TIMEOUT,
                        auto_reconnect=True,
                    )
                    c.connect()
                    self._pool.put(c)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("K线池建连失败: %s", exc)
                    break
            self._ready = True

    def borrow(self) -> MacClient | None:
        self._init()
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            return None

    def giveback(self, c: MacClient | None) -> None:
        if c is not None:
            self._pool.put(c)

    def close(self) -> None:
        while True:
            try:
                c = self._pool.get_nowait()
                try:
                    c.close()
                except Exception:  # noqa: BLE001
                    pass
            except queue.Empty:
                break
        self._ready = False


_kline_pool = _KlinePool(size=3)


def enrich_technical(df: pd.DataFrame, top_n: int = 200, kline_count: int = 120,
                     use_cache: bool = True, max_workers: int = 3) -> tuple[pd.DataFrame, float]:
    """为排名靠前的候选股补充技术面指标（就地新增列），返回 (df, coverage)。

    - 排名：20日动量 ×0.5 + 5日主力净流入占流通比 ×0.5 降序取 top_n；
    - 缓存：当日已计算的 (code, trade_date) 直接复用，命中后零网络请求；
    - 并发：ThreadPoolExecutor + 独立连接池（每连接仅被单线程使用）；
      连接不可用时自动回退全局单例串行路径；
    - coverage：成功取得技术指标的候选占比（0~1），供报告标注数据质量。
    """
    out = df.copy()
    out["realized_vol_ann"] = None
    out["ma_align"] = False
    out["drawdown_from_high"] = None

    rank = (
        out["change_20d_pct"].fillna(0.0) * 0.5
        + out["main_net_5d_pct"].fillna(0.0) * 0.5
    ) if "main_net_5d_pct" in out.columns else out["change_20d_pct"].fillna(0.0)
    top_idx = list(rank.sort_values(ascending=False).head(top_n).index)
    if not top_idx:
        return out, 1.0

    trade_date = now_bj().strftime("%Y-%m-%d")
    pool = _kline_pool if max_workers > 1 else None

    def work(i) -> dict[str, Any] | None:
        m = int(out.at[i, "market"]) if pd.notna(out.at[i, "market"]) else 0
        code = str(out.at[i, "code"])
        if use_cache:
            met = _kline_cache.get(code, trade_date)
            if met is not None:
                return {"i": i, "met": met}
        client = pool.borrow() if pool else None
        try:
            if client is not None:
                met = _kline_metrics_from(client, m, code, kline_count)
            else:
                with call_lock:  # 回退：全局单例串行
                    met = _kline_metrics(m, code, kline_count)
        except Exception as exc:  # noqa: BLE001
            logger.debug("K线富化失败 %s: %s", code, exc)
            return None
        finally:
            if pool:
                pool.giveback(client)
        if use_cache:
            _kline_cache.put(code, trade_date, met)
        return {"i": i, "met": met}

    done = 0
    executor = ThreadPoolExecutor(max_workers=max_workers) if pool is not None else None
    try:
        iterable = executor.map(work, top_idx) if executor is not None else map(work, top_idx)
        for res in iterable:
            if res is None:
                continue
            i, met = res["i"], res["met"]
            out.at[i, "realized_vol_ann"] = met["realized_vol_ann"]
            out.at[i, "ma_align"] = met["ma_align"]
            out.at[i, "drawdown_from_high"] = met["drawdown_from_high"]
            done += 1
    finally:
        if executor is not None:
            executor.shutdown(wait=True)

    coverage = done / len(top_idx) if len(top_idx) else 1.0
    logger.info("技术面富化完成：%d/%d 只（覆盖率 %.0f%%，并发 %d）",
                done, len(top_idx), coverage * 100, max_workers if pool else 1)
    return out, coverage


# ---------------------------------------------------------------------------
# 快照落盘 / 回放 / 兼容入口
# ---------------------------------------------------------------------------

def save_snapshot_csv(df: pd.DataFrame, path: str) -> None:
    """保存原始行情快照为 CSV（离线回放用）。"""
    df.to_csv(path, index=False, encoding="utf-8-sig")


def load_snapshot_csv(path: str) -> SnapshotBundle:
    """从 CSV 读取行情快照（回放），归一化为规范列 + 缺失掩码。

    返回 SnapshotBundle（source="csv-replay"），as_of 取文件 mtime 并标注 local。
    """
    df = pd.read_csv(path, encoding="utf-8-sig")
    df = normalize_frame(df, "csv-replay")
    mtime = now_bj().fromtimestamp(Path(path).stat().st_mtime)
    return _make_bundle(df, "csv-replay", ["csv-replay"],
                        mtime.strftime("%Y-%m-%d %H:%M:%S"), "local")


def fetch_universe(count: int = 12000) -> pd.DataFrame:
    """兼容薄封装：仅返回规范列 DataFrame（新代码请用 fetch_snapshot）。"""
    return fetch_snapshot(count=count).df


def close() -> None:
    """关闭 K 线缓存、K 线连接池与底层 TDX 连接。"""
    try:
        _kline_cache.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        _kline_pool.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        close_tdx()
    except Exception:  # noqa: BLE001
        pass


def _f(v: Any) -> float:
    try:
        val = float(v)
        return val if math.isfinite(val) else float("nan")
    except (TypeError, ValueError):
        return float("nan")
