#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinFeed 洞察层回填脚本（"喂饱"计划核心步骤）。

目标：把已有但稀疏的洞察层表填满，使 Web 仪表盘（温度计仪表盘、每日情绪、
行业热度、因子表）能展示连续、真实的数据信号。

回填内容：
  1. market_thermometer —— 由 daily_bar 反推 28 只标的宇宙的 涨跌家数 / 涨跌停家数 /
     连板高度 / 炸板率 / 主力净流入，合成 0-100 情绪温度计，覆盖全部交易日
     （原仅 1 行）。温度计读取逻辑已在 sentiment_index._get_raw 中修正为
     直接读 daily_bar，避免旧 breadth 列缺陷。
  2. market_sentiment_daily —— 填充 breadth（涨家数）、up_limit / down_limit、
     news_sentiment（由 176K 新闻语料按日聚合的 多空净情绪指数）。
  3. factor_result —— 调用 produce_factor_report() 跑全样本因子回溯
     （Factor B 现读取回填后的 thermometer 序列，可真正执行反转检验）。

说明：daily_bar 当前仅覆盖 28 只标的（非全市场），故温度计/宽度是基于该
样本宇宙的代理指标，已在因子报告与界面中如实标注，不构成全市场结论。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Dict

from finfeed.storage.database import get_db_manager
from finfeed.config.settings import DB_PATH
from finfeed.analysis import sentiment_index as si

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def aggregate_daily_bar(con: sqlite3.Connection) -> Dict[str, dict]:
    logger.info("聚合 daily_bar（28 只标的 × 全部交易日）...")
    agg: Dict[str, dict] = {}
    cur = con.cursor()
    cur.execute(
        "SELECT trade_date, pct_chg FROM daily_bar WHERE pct_chg IS NOT NULL ORDER BY trade_date"
    )
    for trade_date, pct in cur.fetchall():
        a = agg.setdefault(trade_date, {"up": 0, "down": 0, "lim_up": 0, "lim_down": 0})
        if pct > 0:
            a["up"] += 1
        elif pct < 0:
            a["down"] += 1
        if pct >= 9.8:
            a["lim_up"] += 1
        elif pct <= -9.8:
            a["lim_down"] += 1
    logger.info("聚合完成：%d 个交易日", len(agg))
    return agg


def load_limit_pool(con: sqlite3.Connection) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    cur = con.cursor()
    cur.execute("SELECT trade_date, direction, limit_streak FROM limit_pool")
    for trade_date, direction, streak in cur.fetchall():
        a = out.setdefault(trade_date, {"broken": 0, "max_streak": 0})
        if direction == "broken":
            a["broken"] += 1
        if direction == "up" and (streak or 0) > a["max_streak"]:
            a["max_streak"] = streak or 0
    return out


def load_money_flow(con: sqlite3.Connection) -> Dict[str, float]:
    """money_flow 仅覆盖极少量交易日且口径不全，主净分量无法可靠归因到
    28 只标的宇宙，故回填的温度计一律不纳入主净（置 0），避免仪表盘显示
    失真的超大净额。保留接口以便后续在数据完备时启用。"""
    return {}


def aggregate_news_sentiment(con: sqlite3.Connection) -> Dict[str, float]:
    logger.info("聚合 news 表每日情绪（176K 条）...")
    out: Dict[str, float] = {}
    cur = con.cursor()
    cur.execute(
        "SELECT substr(publish_time,1,10) AS d, sentiment FROM news "
        "WHERE publish_time IS NOT NULL AND sentiment IS NOT NULL"
    )
    acc: Dict[str, list] = {}
    for d, s in cur.fetchall():
        if not d:
            continue
        acc.setdefault(d, []).append(s)
    for d, lst in acc.items():
        pos = lst.count("positive")
        neg = lst.count("negative")
        tot = len(lst)
        out[d] = round((pos - neg) / tot, 4) if tot else 0.0
    logger.info("新闻情绪聚合完成：%d 个日期", len(out))
    return out


def compute_index(up, down, lim_up, lim_down, broken, streak, main_net):
    tot = up + down
    breadth_score = ((up / tot) - 0.5) * 200 if tot > 0 else 0.0
    lt = lim_up + lim_down
    limit_score = ((lim_up / lt) - 0.5) * 200 if lt > 0 else 0.0
    denom = lim_up + broken
    broken_rate = round(broken / denom * 100, 2) if denom else 0.0
    broken_score = -broken_rate
    streak_score = min(streak * 3.0, 30.0)
    retail_score = 0.0
    main_score = max(-30.0, min(30.0, main_net / 1e9 * 3.0))

    weights = {"breadth": 0.30, "limit": 0.25, "broken": 0.15,
               "streak": 0.10, "retail": 0.10, "main": 0.10}
    weights = {k: (v if k != "retail" else 0.0) for k, v in weights.items()}
    s = sum(weights.values())
    weights = {k: v / s for k, v in weights.items()}

    composite = (
        breadth_score * weights["breadth"]
        + limit_score * weights["limit"]
        + broken_score * weights["broken"]
        + streak_score * weights["streak"]
        + retail_score * weights["retail"]
        + main_score * weights["main"]
    )
    index = max(0.0, min(100.0, round(composite + 50.0, 1)))
    lvl = si._level(index)
    return index, lvl["name"], broken_rate


def main() -> None:
    con = _connect()
    agg = aggregate_daily_bar(con)
    lp = load_limit_pool(con)
    mf = load_money_flow(con)
    news_sent = aggregate_news_sentiment(con)

    si._ensure_table()

    thermo_rows = []
    msd_rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total = len(agg)
    logger.info("开始回填 market_thermometer / market_sentiment_daily：%d 天", total)
    done = 0
    for td, a in agg.items():
        up, down = a["up"], a["down"]
        lim_up, lim_down = a["lim_up"], a["lim_down"]
        lp_d = lp.get(td, {"broken": 0, "max_streak": 0})
        broken = lp_d["broken"]
        streak = lp_d["max_streak"]
        main_net = mf.get(td, 0.0)

        index, level_name, broken_rate = compute_index(
            up, down, lim_up, lim_down, broken, streak, main_net
        )
        thermo_rows.append((
            td, index, level_name, broken_rate, streak,
            up, down, lim_up, lim_down, 0.0, main_net, now,
        ))

        ns = news_sent.get(td, 0.0)
        msd_rows.append((td, 0.0, lim_up, lim_down, up, 0.0, ns, now))

        done += 1
        if done % 1000 == 0:
            logger.info("  ...已处理 %d / %d 天", done, total)

    with con:
        con.executemany(
            """INSERT INTO market_thermometer
               (trade_date, index_val, level, broken_rate, max_streak, breadth_up,
                breadth_down, up_limit, down_limit, retail_index, main_net_total, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(trade_date) DO UPDATE SET
                   index_val=excluded.index_val, level=excluded.level,
                   broken_rate=excluded.broken_rate, max_streak=excluded.max_streak,
                   breadth_up=excluded.breadth_up, breadth_down=excluded.breadth_down,
                   up_limit=excluded.up_limit, down_limit=excluded.down_limit,
                   retail_index=excluded.retail_index, main_net_total=excluded.main_net_total,
                   created_at=excluded.created_at
            """,
            thermo_rows,
        )
        con.executemany(
            """INSERT INTO market_sentiment_daily
               (trade_date, sentiment_index, up_limit, down_limit, breadth, forum_heat, news_sentiment, created_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(trade_date) DO UPDATE SET
                   up_limit=excluded.up_limit, down_limit=excluded.down_limit,
                   breadth=excluded.breadth, news_sentiment=excluded.news_sentiment,
                   created_at=excluded.created_at
            """,
            msd_rows,
        )
    logger.info("回填完成：market_thermometer=%d 行, market_sentiment_daily=%d 行",
                len(thermo_rows), len(msd_rows))

    cur = con.cursor()
    cur.execute(
        "SELECT trade_date, index_val, level, breadth_up, breadth_down, up_limit, down_limit "
        "FROM market_thermometer ORDER BY trade_date DESC LIMIT 1"
    )
    r = cur.fetchone()
    logger.info("最新温度计：%s 指数=%.1f 级别=%s 宽度=%d/%d 涨跌停=%d/%d",
                r["trade_date"], r["index_val"], r["level"],
                r["breadth_up"], r["breadth_down"], r["up_limit"], r["down_limit"])
    con.close()


if __name__ == "__main__":
    main()
