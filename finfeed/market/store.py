#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富事实层 —— 存储层（建表 + 幂等写入）

风格对齐 storage/ 现有模块：以 (code, trade_date) / (trade_date, code, direction) 为主键，
upsert 幂等，缺失一天即回补（失败语义与新闻层不同，见报告 4 表）。

表清单（见报告 8）：
  daily_bar      日线（回测/归因核心）
  news_stock_link 新闻↔个股关联（实体识别产出，场景1/2/4 前置）
  limit_pool     涨跌停池（填 market_sentiment_daily 原料）
  money_flow     个股资金流
  billboard      龙虎榜
另给 stock_meta 增加 alias 列（别名 JSON 数组，支撑实体识别）。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from finfeed.storage.database import get_db_manager

logger = logging.getLogger("news_monitor")


# ---------------------------------------------------------------------------
# 建表
# ---------------------------------------------------------------------------
def ensure_market_tables() -> None:
    """创建事实层所有表（幂等）。在 market service 启动时调用一次。"""
    db = get_db_manager()
    with db.get_db() as c:
        # stock_meta 扩展列
        _add_column(c, "stock_meta", "alias", "TEXT DEFAULT '[]'")
        _add_column(c, "stock_meta", "list_date", "TEXT DEFAULT ''")
        # 证券类型（剔除新三板/B股的判别依据）与板块归类
        _add_column(c, "stock_meta", "security_type", "TEXT DEFAULT ''")
        _add_column(c, "stock_meta", "board", "TEXT DEFAULT ''")
        # 是否在市：0 表示已退市/长期停牌，批量采集必须跳过，否则请求量放大数倍
        _add_column(c, "stock_meta", "is_active", "INTEGER DEFAULT 1")

        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_bar (
                code TEXT,
                trade_date TEXT,
                open REAL, high REAL, low REAL, close REAL,
                volume INTEGER, amount REAL,
                pct_chg REAL, amplitude REAL, turnover REAL,
                fq_type INTEGER DEFAULT 1,
                PRIMARY KEY (code, trade_date, fq_type)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_bar_date ON daily_bar(trade_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bar_code ON daily_bar(code)")

        # ---- 聚合表（此前无 DDL，仅在既有库中存在；此处补齐以自洽）----
        c.execute("""
            CREATE TABLE IF NOT EXISTS sector_members (
                sector_code TEXT,
                sector_name TEXT,
                sector_type TEXT,
                code TEXT,
                name TEXT DEFAULT '',
                weight REAL DEFAULT 0.0,
                PRIMARY KEY (sector_code, code)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sm_code ON sector_members(code)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sm_sector ON sector_members(sector_code)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS stock_sentiment (
                code TEXT,
                name TEXT DEFAULT '',
                trade_date TEXT,
                sentiment_score REAL DEFAULT 0.0,
                sentiment_label TEXT DEFAULT 'neutral',
                heat REAL DEFAULT 0.0,
                mention_count INTEGER DEFAULT 0,
                pos_mentions INTEGER DEFAULT 0,
                neg_mentions INTEGER DEFAULT 0,
                source TEXT DEFAULT '',
                created_at TEXT,
                PRIMARY KEY (code, trade_date, source)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS sector_sentiment (
                sector_code TEXT,
                sector_name TEXT,
                sector_type TEXT,
                trade_date TEXT,
                sentiment_score REAL DEFAULT 0.0,
                heat REAL DEFAULT 0.0,
                member_count INTEGER DEFAULT 0,
                top_stocks TEXT DEFAULT '[]',
                created_at TEXT,
                PRIMARY KEY (sector_code, trade_date)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS market_sentiment_daily (
                trade_date TEXT PRIMARY KEY,
                sentiment_index REAL DEFAULT 0.0,
                up_limit INTEGER DEFAULT 0,
                down_limit INTEGER DEFAULT 0,
                breadth INTEGER DEFAULT 0,
                forum_heat REAL DEFAULT 0.0,
                news_sentiment REAL DEFAULT 0.0,
                created_at TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS forum_sentiment_daily (
                trade_date TEXT PRIMARY KEY,
                retail_index REAL DEFAULT 0.0,
                heat REAL DEFAULT 0.0,
                up_count INTEGER DEFAULT 0,
                down_count INTEGER DEFAULT 0,
                neutral_count INTEGER DEFAULT 0,
                volume INTEGER DEFAULT 0,
                stock_coverage INTEGER DEFAULT 0,
                active_sources TEXT DEFAULT '[]',
                top_stocks TEXT DEFAULT '[]',
                created_at TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS news_stock_link (
                news_id INTEGER,
                code TEXT,
                match_type TEXT DEFAULT 'code',
                confidence REAL DEFAULT 1.0,
                PRIMARY KEY (news_id, code)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_link_code ON news_stock_link(code)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_link_news ON news_stock_link(news_id)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS limit_pool (
                trade_date TEXT,
                code TEXT,
                name TEXT DEFAULT '',
                direction TEXT,
                first_limit_time TEXT DEFAULT '',
                last_limit_time TEXT DEFAULT '',
                open_times INTEGER DEFAULT 0,
                limit_amount REAL DEFAULT 0.0,
                circ_mv REAL DEFAULT 0.0,
                reason TEXT DEFAULT '',
                PRIMARY KEY (trade_date, code, direction)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_limit_date ON limit_pool(trade_date, direction)")
        # push2ex 池子的富字段：连板梯队与封板质量分析必需
        _add_column(c, "limit_pool", "limit_streak", "INTEGER DEFAULT 0")   # 连板数
        _add_column(c, "limit_pool", "pct_chg", "REAL DEFAULT 0.0")         # 涨跌幅 %
        _add_column(c, "limit_pool", "price", "REAL DEFAULT 0.0")           # 最新价 元
        _add_column(c, "limit_pool", "turnover", "REAL DEFAULT 0.0")        # 换手率 %
        _add_column(c, "limit_pool", "amount", "REAL DEFAULT 0.0")          # 成交额 亿元
        _add_column(c, "limit_pool", "total_mv", "REAL DEFAULT 0.0")        # 总市值 亿元

        c.execute("""
            CREATE TABLE IF NOT EXISTS money_flow (
                code TEXT,
                trade_date TEXT,
                main_net REAL DEFAULT 0.0,
                super_net REAL DEFAULT 0.0,
                big_net REAL DEFAULT 0.0,
                mid_net REAL DEFAULT 0.0,
                small_net REAL DEFAULT 0.0,
                PRIMARY KEY (code, trade_date)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_mf_date ON money_flow(trade_date)")
        # datacenter RPT_DMSK_TS_STOCKNEW 附带的行情/参与度字段
        _add_column(c, "money_flow", "name", "TEXT DEFAULT ''")
        _add_column(c, "money_flow", "close_price", "REAL DEFAULT 0.0")
        _add_column(c, "money_flow", "pct_chg", "REAL DEFAULT 0.0")
        _add_column(c, "money_flow", "turnover", "REAL DEFAULT 0.0")
        _add_column(c, "money_flow", "main_ratio", "REAL DEFAULT 0.0")      # 主力净占比
        _add_column(c, "money_flow", "org_participate", "REAL DEFAULT 0.0") # 机构参与度
        _add_column(c, "money_flow", "source", "TEXT DEFAULT ''")           # datacenter / push2

        c.execute("""
            CREATE TABLE IF NOT EXISTS billboard (
                trade_date TEXT,
                code TEXT,
                name TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                buy_amount REAL DEFAULT 0.0,
                sell_amount REAL DEFAULT 0.0,
                net_amount REAL DEFAULT 0.0,
                turnover_ratio REAL DEFAULT 0.0,
                PRIMARY KEY (trade_date, code, reason)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_bb_date ON billboard(trade_date)")
        # reason 存 EXPLANATION（上榜原因类别，可分组统计）；detail 存 EXPLAIN（席位解读）
        _add_column(c, "billboard", "detail", "TEXT DEFAULT ''")
        _add_column(c, "billboard", "close_price", "REAL DEFAULT 0.0")
        _add_column(c, "billboard", "pct_chg", "REAL DEFAULT 0.0")
        _add_column(c, "billboard", "deal_amount", "REAL DEFAULT 0.0")   # 龙虎榜成交额
        _add_column(c, "billboard", "accum_amount", "REAL DEFAULT 0.0")  # 全日成交额
        _add_column(c, "billboard", "free_mv", "REAL DEFAULT 0.0")       # 流通市值

        # ---- 本次新增整合的三张事实表（均来自 datacenter，无限流风险）----
        c.execute("""
            CREATE TABLE IF NOT EXISTS margin_detail (
                trade_date TEXT,
                code TEXT,
                name TEXT DEFAULT '',
                market TEXT DEFAULT '',
                fin_balance REAL DEFAULT 0.0,      -- 融资余额
                fin_buy REAL DEFAULT 0.0,          -- 融资买入额
                fin_net REAL DEFAULT 0.0,          -- 融资净买入
                short_balance REAL DEFAULT 0.0,    -- 融券余额
                short_volume REAL DEFAULT 0.0,     -- 融券余量
                total_balance REAL DEFAULT 0.0,    -- 融资融券余额
                balance_ratio REAL DEFAULT 0.0,    -- 融资余额占流通市值比 %
                pct_chg REAL DEFAULT 0.0,
                PRIMARY KEY (trade_date, code)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_margin_date ON margin_detail(trade_date)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS earnings_forecast (
                code TEXT,
                report_date TEXT,                  -- 报告期
                notice_date TEXT,                  -- 公告日
                name TEXT DEFAULT '',
                forecast_type TEXT DEFAULT '',     -- 预增/略增/扭亏/预减...
                forecast_content TEXT DEFAULT '',
                profit_low REAL DEFAULT 0.0,
                profit_high REAL DEFAULT 0.0,
                increase_low REAL DEFAULT 0.0,     -- 同比增幅下限 %
                increase_high REAL DEFAULT 0.0,
                change_reason TEXT DEFAULT '',
                is_latest INTEGER DEFAULT 1,
                PRIMARY KEY (code, report_date, notice_date)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_fc_notice ON earnings_forecast(notice_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_fc_code ON earnings_forecast(code)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS ipo_calendar (
                code TEXT PRIMARY KEY,
                apply_code TEXT DEFAULT '',
                name TEXT DEFAULT '',
                apply_date TEXT DEFAULT '',        -- 申购日
                listing_date TEXT DEFAULT '',      -- 上市日
                ballot_date TEXT DEFAULT '',       -- 中签号公布
                pay_date TEXT DEFAULT '',          -- 缴款日
                issue_price REAL DEFAULT 0.0,
                apply_upper REAL DEFAULT 0.0,      -- 网上申购上限(股)
                market TEXT DEFAULT '',
                industry TEXT DEFAULT '',
                issue_pe REAL DEFAULT 0.0,
                ballot_rate REAL DEFAULT 0.0       -- 中签率 %
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_ipo_apply ON ipo_calendar(apply_date)")

        # ---- 同花顺热榜快照（按交易日自动采集，支撑历史日期回看）----
        c.execute("""
            CREATE TABLE IF NOT EXISTS ths_hotrank (
                trade_date TEXT,
                list_type TEXT,
                period TEXT,
                rank INTEGER,
                code TEXT,
                name TEXT DEFAULT '',
                market TEXT DEFAULT '',
                heat REAL DEFAULT 0.0,
                change_pct REAL DEFAULT 0.0,
                rank_chg INTEGER DEFAULT 0,
                popularity_tag TEXT DEFAULT '',
                concept_tags TEXT DEFAULT '[]',
                topic TEXT DEFAULT '',
                collected_at TEXT DEFAULT '',
                category TEXT DEFAULT 'stock',
                extra_json TEXT DEFAULT '[]',
                PRIMARY KEY (trade_date, list_type, period, code)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_thr_date ON ths_hotrank(trade_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_thr_lp ON ths_hotrank(list_type, period)")
        # 兼容已存在的库：补充新列（幂等，必须在建索引前执行）
        _add_column(c, "ths_hotrank", "category", "TEXT DEFAULT 'stock'")
        _add_column(c, "ths_hotrank", "extra_json", "TEXT DEFAULT '[]'")
        c.execute("CREATE INDEX IF NOT EXISTS idx_thr_cat ON ths_hotrank(category)")

        # ---- 同花顺「涨停聚焦」四模块快照（按交易日自动采集，支撑历史回看）----
        c.execute("""
            CREATE TABLE IF NOT EXISTS ths_limitup_pool (
                trade_date TEXT,
                pool_type TEXT,
                rank INTEGER DEFAULT 0,
                code TEXT,
                name TEXT DEFAULT '',
                price REAL DEFAULT 0.0,
                change_pct REAL DEFAULT 0.0,
                amplitude REAL DEFAULT 0.0,
                reason TEXT DEFAULT '',
                board TEXT DEFAULT '',
                continue_day_cnt INTEGER DEFAULT 0,
                limit_up_time TEXT DEFAULT '',
                main_net_amount REAL DEFAULT 0.0,
                effective_circulation REAL DEFAULT 0.0,
                turnover_ratio REAL DEFAULT 0.0,
                is_st INTEGER DEFAULT 0,
                is_new INTEGER DEFAULT 0,
                market_code TEXT DEFAULT '',
                detail_json TEXT DEFAULT '{}',
                PRIMARY KEY (trade_date, pool_type, code)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_tlp_date ON ths_limitup_pool(trade_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tlp_dp ON ths_limitup_pool(trade_date, pool_type)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS ths_limitup_ladder (
                trade_date TEXT,
                height INTEGER,
                number INTEGER DEFAULT 0,
                code TEXT,
                name TEXT DEFAULT '',
                market_id TEXT DEFAULT '',
                continue_num INTEGER DEFAULT 0,
                PRIMARY KEY (trade_date, height, code)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_tll_date ON ths_limitup_ladder(trade_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tll_dh ON ths_limitup_ladder(trade_date, height)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS ths_limitup_wind (
                trade_date TEXT,
                tab_name TEXT,
                average_change REAL DEFAULT 0.0,
                stock_num INTEGER DEFAULT 0,
                stock_code TEXT,
                stock_name TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                price REAL DEFAULT 0.0,
                change REAL DEFAULT 0.0,
                five_rise REAL DEFAULT 0.0,
                tags TEXT DEFAULT '',
                rank INTEGER DEFAULT 0,
                PRIMARY KEY (trade_date, tab_name, stock_code)
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_tlw_date ON ths_limitup_wind(trade_date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tlw_tab ON ths_limitup_wind(trade_date, tab_name)")

        c.execute("""
            CREATE TABLE IF NOT EXISTS ths_limitup_sentiment (
                trade_date TEXT PRIMARY KEY,
                turnover_pre REAL DEFAULT 0.0,
                turnover_now REAL DEFAULT 0.0,
                turnover_flag TEXT DEFAULT '',
                north_flow TEXT DEFAULT '',
                limit_up_pre INTEGER DEFAULT 0,
                limit_up_now INTEGER DEFAULT 0,
                limit_up_flag TEXT DEFAULT '',
                rise INTEGER DEFAULT 0,
                fall INTEGER DEFAULT 0,
                deuce INTEGER DEFAULT 0,
                rise_limit INTEGER DEFAULT 0,
                rise_down INTEGER DEFAULT 0,
                hgt_market_status TEXT DEFAULT '',
                config_start_date TEXT DEFAULT '',
                trade_status TEXT DEFAULT '',
                trade_status_ts TEXT DEFAULT '',
                collected_at TEXT DEFAULT ''
            )
        """)


def _add_column(c, table: str, col: str, definition: str) -> None:
    try:
        existing = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in existing:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
    except Exception as e:  # noqa: BLE001
        logger.debug(f"列 {col} 已存在或添加失败: {e}")


# ---------------------------------------------------------------------------
# 写：股票池（扩展版，含 alias）
# ---------------------------------------------------------------------------
def upsert_stock_meta_full(rows: List[Dict[str, Any]]) -> int:
    """rows: {code, name, industry, market, alias?, list_date?, security_type?, board?}

    注意：不在此处写 is_active —— 在市状态由 set_active_flags() 依据当日全市场
    行情快照单独刷新，避免名录报表（含已退市标的）污染批量采集的股票范围。
    """
    if not rows:
        return 0
    db = get_db_manager()
    now = _now()
    data = [
        (r["code"], r.get("name", ""), r.get("industry", ""), r.get("market", ""),
         json.dumps(r.get("alias") or [], ensure_ascii=False), r.get("list_date", ""),
         r.get("security_type", ""), r.get("board", ""), now)
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO stock_meta (code, name, industry, market, alias, list_date,
                   security_type, board, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code) DO UPDATE SET
                   name=excluded.name, industry=excluded.industry, market=excluded.market,
                   alias=excluded.alias, list_date=excluded.list_date,
                   security_type=excluded.security_type, board=excluded.board,
                   updated_at=excluded.updated_at
            """,
            data,
        )
        return len(data)


def set_active_flags(active_codes: List[str]) -> Dict[str, int]:
    """按当日全市场快照刷新 stock_meta.is_active。

    Returns: {'active': n, 'inactive': m}
    """
    if not active_codes:
        return {"active": 0, "inactive": 0}
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("CREATE TEMP TABLE IF NOT EXISTS _active(code TEXT PRIMARY KEY)")
        c.execute("DELETE FROM _active")
        c.executemany("INSERT OR IGNORE INTO _active(code) VALUES (?)",
                      [(x,) for x in active_codes])
        c.execute("UPDATE stock_meta SET is_active = 0")
        c.execute("UPDATE stock_meta SET is_active = 1 "
                  "WHERE code IN (SELECT code FROM _active)")
        n_act = c.execute("SELECT COUNT(*) FROM stock_meta WHERE is_active = 1").fetchone()[0]
        n_ina = c.execute("SELECT COUNT(*) FROM stock_meta WHERE is_active = 0").fetchone()[0]
        c.execute("DROP TABLE IF EXISTS _active")
    return {"active": n_act, "inactive": n_ina}


def purge_stock_meta(valid_codes: List[str]) -> Dict[str, int]:
    """删除 stock_meta 中不属于 A 股名录的历史残留记录。

    ⚠️ 存在必要性：旧实现把 RPT_F10_BASIC_ORGINFO 的 24759 条全量落库，
    其中 15966 条是新三板、313 条老三板。仅靠 is_active=0 标记不足够——
    universe.fetch_all_board_members() 会用 `SELECT code FROM stock_meta`
    构建题材映射白名单，残留记录会让 sector_members 继续被污染。

    只在 valid_codes 达到健康规模时才执行，避免数据源异常时误删全表。
    """
    if len(valid_codes) < 7000:
        logger.warning(f"purge_stock_meta: 名录仅 {len(valid_codes)} 条，低于安全阈值，跳过清理")
        return {"deleted": 0, "kept": 0}
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("CREATE TEMP TABLE IF NOT EXISTS _valid(code TEXT PRIMARY KEY)")
        c.execute("DELETE FROM _valid")
        c.executemany("INSERT OR IGNORE INTO _valid(code) VALUES (?)",
                      [(x,) for x in valid_codes])
        n_del = c.execute(
            "SELECT COUNT(*) FROM stock_meta WHERE code NOT IN (SELECT code FROM _valid)"
        ).fetchone()[0]
        c.execute("DELETE FROM stock_meta WHERE code NOT IN (SELECT code FROM _valid)")
        # 同步清理板块成分中的孤儿映射
        c.execute("DELETE FROM sector_members WHERE code NOT IN (SELECT code FROM _valid)")
        n_keep = c.execute("SELECT COUNT(*) FROM stock_meta").fetchone()[0]
        c.execute("DROP TABLE IF EXISTS _valid")
    if n_del:
        logger.info(f"stock_meta 清理非 A 股残留 {n_del} 条，保留 {n_keep} 条")
    return {"deleted": n_del, "kept": n_keep}


def get_active_codes(board: Optional[str] = None) -> List[str]:
    """在市 A 股代码列表（批量采集的唯一权威入口）。"""
    db = get_db_manager()
    sql = "SELECT code FROM stock_meta WHERE is_active = 1"
    params: List[Any] = []
    if board:
        sql += " AND board = ?"
        params.append(board)
    sql += " ORDER BY code"
    with db.get_db() as c:
        c.execute(sql, params)
        return [r["code"] for r in c.fetchall()]


def get_stock_meta_alias(code: str) -> List[str]:
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT alias FROM stock_meta WHERE code = ?", (code,))
        row = c.fetchone()
    if not row or not row["alias"]:
        return []
    try:
        return json.loads(row["alias"])
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# 写：新闻↔个股关联
# ---------------------------------------------------------------------------
def upsert_news_stock_link(rows: List[tuple]) -> int:
    """rows: (news_id, code, match_type, confidence)"""
    if not rows:
        return 0
    db = get_db_manager()
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO news_stock_link (news_id, code, match_type, confidence)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(news_id, code) DO UPDATE SET
                   match_type=excluded.match_type, confidence=excluded.confidence
            """,
            rows,
        )
        return len(rows)


def get_news_stocks(news_id: int) -> List[str]:
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT code FROM news_stock_link WHERE news_id = ?", (news_id,))
        return [r["code"] for r in c.fetchall()]


# ---------------------------------------------------------------------------
# 写：涨跌停池
# ---------------------------------------------------------------------------
def upsert_limit_pool(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["trade_date"], r["code"], r.get("name", ""), r["direction"],
         r.get("first_limit_time", ""), r.get("last_limit_time", ""),
         r.get("open_times", 0), r.get("limit_amount", 0.0), r.get("circ_mv", 0.0),
         r.get("reason", ""), int(r.get("limit_streak", 0) or 0), r.get("pct_chg", 0.0),
         r.get("price", 0.0), r.get("turnover", 0.0), r.get("amount", 0.0),
         r.get("total_mv", 0.0))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO limit_pool (trade_date, code, name, direction, first_limit_time,
                   last_limit_time, open_times, limit_amount, circ_mv, reason,
                   limit_streak, pct_chg, price, turnover, amount, total_mv)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_date, code, direction) DO UPDATE SET
                   name=excluded.name, first_limit_time=excluded.first_limit_time,
                   last_limit_time=excluded.last_limit_time, open_times=excluded.open_times,
                   limit_amount=excluded.limit_amount, circ_mv=excluded.circ_mv,
                   reason=excluded.reason, limit_streak=excluded.limit_streak,
                   pct_chg=excluded.pct_chg, price=excluded.price,
                   turnover=excluded.turnover, amount=excluded.amount,
                   total_mv=excluded.total_mv
            """,
            data,
        )
        return len(data)


def get_limit_pool(trade_date: str, direction: str = "up") -> List[Dict[str, Any]]:
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT * FROM limit_pool WHERE trade_date = ? AND direction = ? ORDER BY limit_amount DESC",
            (trade_date, direction),
        )
        return [dict(r) for r in c.fetchall()]


# ---------------------------------------------------------------------------
# 写：日线
# ---------------------------------------------------------------------------
def upsert_daily_bar(rows: List[Dict[str, Any]]) -> int:
    """rows: {code, trade_date, open, high, low, close, volume, amount,
              pct_chg, amplitude, turnover, fq_type?}"""
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["code"], r["trade_date"], r.get("open", 0.0), r.get("high", 0.0),
         r.get("low", 0.0), r.get("close", 0.0), int(r.get("volume", 0) or 0),
         r.get("amount", 0.0), r.get("pct_chg", 0.0), r.get("amplitude", 0.0),
         r.get("turnover", 0.0), r.get("fq_type", 1))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO daily_bar (code, trade_date, open, high, low, close, volume, amount,
                   pct_chg, amplitude, turnover, fq_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code, trade_date, fq_type) DO UPDATE SET
                   open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                   volume=excluded.volume, amount=excluded.amount, pct_chg=excluded.pct_chg,
                   amplitude=excluded.amplitude, turnover=excluded.turnover
            """,
            data,
        )
        return len(data)


def get_daily_bar(code: str, start: Optional[str] = None, end: Optional[str] = None) -> List[Dict[str, Any]]:
    db = get_db_manager()
    with db.get_db() as c:
        cond = ["code = ?", "fq_type = 1"]
        params: List[Any] = [code]
        if start:
            cond.append("trade_date >= ?"); params.append(start)
        if end:
            cond.append("trade_date <= ?"); params.append(end)
        c.execute(
            f"SELECT * FROM daily_bar WHERE {' AND '.join(cond)} ORDER BY trade_date",
            params,
        )
        return [dict(r) for r in c.fetchall()]


# ---------------------------------------------------------------------------
# 写：资金流 / 龙虎榜
# ---------------------------------------------------------------------------
def upsert_money_flow(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["code"], r["trade_date"], r.get("main_net", 0.0), r.get("super_net", 0.0),
         r.get("big_net", 0.0), r.get("mid_net", 0.0), r.get("small_net", 0.0),
         r.get("name", ""), r.get("close_price", 0.0), r.get("pct_chg", 0.0),
         r.get("turnover", 0.0), r.get("main_ratio", 0.0),
         r.get("org_participate", 0.0), r.get("source", ""))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO money_flow (code, trade_date, main_net, super_net, big_net,
                   mid_net, small_net, name, close_price, pct_chg, turnover,
                   main_ratio, org_participate, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code, trade_date) DO UPDATE SET
                   main_net=excluded.main_net, super_net=excluded.super_net,
                   big_net=excluded.big_net, mid_net=excluded.mid_net,
                   small_net=excluded.small_net, name=excluded.name,
                   close_price=excluded.close_price, pct_chg=excluded.pct_chg,
                   turnover=excluded.turnover, main_ratio=excluded.main_ratio,
                   org_participate=excluded.org_participate, source=excluded.source
            """,
            data,
        )
        return len(data)


# ---------------------------------------------------------------------------
# 写：融资融券 / 业绩预告 / 新股日历（本次新增整合）
# ---------------------------------------------------------------------------
def upsert_margin_detail(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["trade_date"], r["code"], r.get("name", ""), r.get("market", ""),
         r.get("fin_balance", 0.0), r.get("fin_buy", 0.0), r.get("fin_net", 0.0),
         r.get("short_balance", 0.0), r.get("short_volume", 0.0),
         r.get("total_balance", 0.0), r.get("balance_ratio", 0.0), r.get("pct_chg", 0.0))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO margin_detail (trade_date, code, name, market, fin_balance,
                   fin_buy, fin_net, short_balance, short_volume, total_balance,
                   balance_ratio, pct_chg)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_date, code) DO UPDATE SET
                   name=excluded.name, market=excluded.market,
                   fin_balance=excluded.fin_balance, fin_buy=excluded.fin_buy,
                   fin_net=excluded.fin_net, short_balance=excluded.short_balance,
                   short_volume=excluded.short_volume, total_balance=excluded.total_balance,
                   balance_ratio=excluded.balance_ratio, pct_chg=excluded.pct_chg
            """,
            data,
        )
        return len(data)


def upsert_earnings_forecast(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["code"], r.get("report_date", ""), r.get("notice_date", ""), r.get("name", ""),
         r.get("forecast_type", ""), r.get("forecast_content", ""),
         r.get("profit_low", 0.0), r.get("profit_high", 0.0),
         r.get("increase_low", 0.0), r.get("increase_high", 0.0),
         r.get("change_reason", ""), int(r.get("is_latest", 1) or 0))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO earnings_forecast (code, report_date, notice_date, name,
                   forecast_type, forecast_content, profit_low, profit_high,
                   increase_low, increase_high, change_reason, is_latest)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code, report_date, notice_date) DO UPDATE SET
                   name=excluded.name, forecast_type=excluded.forecast_type,
                   forecast_content=excluded.forecast_content,
                   profit_low=excluded.profit_low, profit_high=excluded.profit_high,
                   increase_low=excluded.increase_low, increase_high=excluded.increase_high,
                   change_reason=excluded.change_reason, is_latest=excluded.is_latest
            """,
            data,
        )
        return len(data)


def upsert_ipo_calendar(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["code"], r.get("apply_code", ""), r.get("name", ""), r.get("apply_date", ""),
         r.get("listing_date", ""), r.get("ballot_date", ""), r.get("pay_date", ""),
         r.get("issue_price", 0.0), r.get("apply_upper", 0.0), r.get("market", ""),
         r.get("industry", ""), r.get("issue_pe", 0.0), r.get("ballot_rate", 0.0))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO ipo_calendar (code, apply_code, name, apply_date, listing_date,
                   ballot_date, pay_date, issue_price, apply_upper, market, industry,
                   issue_pe, ballot_rate)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(code) DO UPDATE SET
                   apply_code=excluded.apply_code, name=excluded.name,
                   apply_date=excluded.apply_date, listing_date=excluded.listing_date,
                   ballot_date=excluded.ballot_date, pay_date=excluded.pay_date,
                   issue_price=excluded.issue_price, apply_upper=excluded.apply_upper,
                   market=excluded.market, industry=excluded.industry,
                   issue_pe=excluded.issue_pe, ballot_rate=excluded.ballot_rate
            """,
            data,
        )
        return len(data)


def get_margin_detail(trade_date: str, limit: int = 50) -> List[Dict[str, Any]]:
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT * FROM margin_detail WHERE trade_date = ? "
                  "ORDER BY fin_net DESC LIMIT ?", (trade_date, limit))
        return [dict(r) for r in c.fetchall()]


def get_upcoming_ipo(start: str, end: str) -> List[Dict[str, Any]]:
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT * FROM ipo_calendar WHERE apply_date >= ? AND apply_date <= ? "
                  "ORDER BY apply_date", (start, end))
        return [dict(r) for r in c.fetchall()]


def upsert_billboard(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["trade_date"], r["code"], r.get("name", ""), r.get("reason", ""),
         r.get("buy_amount", 0.0), r.get("sell_amount", 0.0), r.get("net_amount", 0.0),
         r.get("turnover_ratio", 0.0), r.get("detail", ""), r.get("close_price", 0.0),
         r.get("pct_chg", 0.0), r.get("deal_amount", 0.0), r.get("accum_amount", 0.0),
         r.get("free_mv", 0.0))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO billboard (trade_date, code, name, reason, buy_amount, sell_amount,
                   net_amount, turnover_ratio, detail, close_price, pct_chg,
                   deal_amount, accum_amount, free_mv)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_date, code, reason) DO UPDATE SET
                   name=excluded.name, buy_amount=excluded.buy_amount,
                   sell_amount=excluded.sell_amount, net_amount=excluded.net_amount,
                   turnover_ratio=excluded.turnover_ratio, detail=excluded.detail,
                   close_price=excluded.close_price, pct_chg=excluded.pct_chg,
                   deal_amount=excluded.deal_amount, accum_amount=excluded.accum_amount,
                   free_mv=excluded.free_mv
            """,
            data,
        )
        return len(data)


def get_billboard(trade_date: str) -> List[Dict[str, Any]]:
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT * FROM billboard WHERE trade_date = ? ORDER BY net_amount DESC", (trade_date,))
        return [dict(r) for r in c.fetchall()]


# ===========================================================================
# 读：全维度事实查询（供 Web 事实层面板）
#
# 设计约束：
#   1. 全部为**只读**查询，绝不触发任何网络采集。页面刷新不应造成东财施压。
#   2. 所有排行类查询强制 LIMIT，避免把 5191 行资金流一次性塞进浏览器。
#   3. 金额单位一律保持库内原始单位（元），格式化交给前端，避免精度二次损失。
# ===========================================================================

# 允许排序的列白名单（防 SQL 注入；这些值来自 URL query）
_MF_ORDER = {
    "main_net": "main_net", "super_net": "super_net", "big_net": "big_net",
    "pct_chg": "pct_chg", "turnover": "turnover",
    "main_ratio": "main_ratio", "org_participate": "org_participate",
}
_MARGIN_ORDER = {
    "fin_net": "fin_net", "fin_balance": "fin_balance", "fin_buy": "fin_buy",
    "short_balance": "short_balance", "total_balance": "total_balance",
    "balance_ratio": "balance_ratio", "pct_chg": "pct_chg",
}
_FC_ORDER = {
    "increase_high": "increase_high", "increase_low": "increase_low",
    "profit_high": "profit_high", "notice_date": "notice_date",
}


def latest_date(table: str, col: str = "trade_date",
                where: str = "") -> Optional[str]:
    """返回某表最近一个有数据的日期。table/col 均为内部常量，不接受外部输入。"""
    db = get_db_manager()
    try:
        with db.get_db() as c:
            c.execute(f"SELECT MAX({col}) AS d FROM {table} {where}")
            row = c.fetchone()
            return row["d"] if row and row["d"] else None
    except Exception:  # noqa: BLE001  表不存在时静默
        return None


def get_money_flow(trade_date: str, direction: str = "in",
                   order_by: str = "main_net", limit: int = 50,
                   board: Optional[str] = None) -> List[Dict[str, Any]]:
    """资金流排行。

    direction: in=净流入（降序）/ out=净流出（升序）/ all=按 order_by 降序
    board:     可选按 stock_meta.board 过滤（主板/创业板/科创板/北交所/风险警示）
    """
    col = _MF_ORDER.get(order_by, "main_net")
    db = get_db_manager()
    params: List[Any] = [trade_date]
    join = ""
    cond = "m.trade_date = ?"
    if board:
        join = "JOIN stock_meta s ON s.code = m.code"
        cond += " AND s.board = ?"
        params.append(board)
    if direction == "in":
        cond += f" AND m.{col} > 0"
        order = f"m.{col} DESC"
    elif direction == "out":
        cond += f" AND m.{col} < 0"
        order = f"m.{col} ASC"
    else:
        order = f"m.{col} DESC"
    params.append(int(limit))
    with db.get_db() as c:
        c.execute(
            f"SELECT m.* FROM money_flow m {join} WHERE {cond} "
            f"ORDER BY {order} LIMIT ?",
            params,
        )
        return [dict(r) for r in c.fetchall()]


def get_money_flow_summary(trade_date: str) -> Dict[str, Any]:
    """全市场资金流总览（净流入/流出家数、主力合计、机构参与度均值）。"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN main_net > 0 THEN 1 ELSE 0 END) AS in_cnt,
                      SUM(CASE WHEN main_net < 0 THEN 1 ELSE 0 END) AS out_cnt,
                      SUM(main_net)  AS main_sum,
                      SUM(super_net) AS super_sum,
                      SUM(big_net)   AS big_sum,
                      AVG(org_participate) AS org_avg,
                      AVG(turnover)  AS turnover_avg
               FROM money_flow WHERE trade_date = ?""",
            (trade_date,),
        )
        row = c.fetchone()
        return dict(row) if row else {}


def get_margin_rank(trade_date: str, order_by: str = "fin_net",
                    desc: bool = True, limit: int = 50) -> List[Dict[str, Any]]:
    """两融排行。默认按融资净买入降序。"""
    col = _MARGIN_ORDER.get(order_by, "fin_net")
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            f"SELECT * FROM margin_detail WHERE trade_date = ? "
            f"ORDER BY {col} {'DESC' if desc else 'ASC'} LIMIT ?",
            (trade_date, int(limit)),
        )
        return [dict(r) for r in c.fetchall()]


def get_margin_summary(trade_date: str) -> Dict[str, Any]:
    """两融总量：融资余额合计、融券余额合计、净买入合计、标的数。"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """SELECT COUNT(*) AS total,
                      SUM(fin_balance)   AS fin_balance_sum,
                      SUM(fin_buy)       AS fin_buy_sum,
                      SUM(fin_net)       AS fin_net_sum,
                      SUM(short_balance) AS short_balance_sum,
                      SUM(total_balance) AS total_balance_sum,
                      SUM(CASE WHEN fin_net > 0 THEN 1 ELSE 0 END) AS net_in_cnt
               FROM margin_detail WHERE trade_date = ?""",
            (trade_date,),
        )
        row = c.fetchone()
        return dict(row) if row else {}


def get_earnings_forecast(ftype: Optional[str] = None, latest_only: bool = True,
                          order_by: str = "increase_high",
                          limit: int = 100) -> List[Dict[str, Any]]:
    """业绩预告。ftype 为预告类型（预增/首亏/扭亏/预减…），None 为全部。"""
    col = _FC_ORDER.get(order_by, "increase_high")
    db = get_db_manager()
    cond: List[str] = []
    params: List[Any] = []
    if latest_only:
        cond.append("is_latest = 1")
    if ftype:
        cond.append("forecast_type = ?")
        params.append(ftype)
    where = f"WHERE {' AND '.join(cond)}" if cond else ""
    params.append(int(limit))
    with db.get_db() as c:
        c.execute(
            f"SELECT * FROM earnings_forecast {where} "
            f"ORDER BY {col} DESC NULLS LAST LIMIT ?",
            params,
        )
        return [dict(r) for r in c.fetchall()]


def get_forecast_type_stats(latest_only: bool = True) -> List[Dict[str, Any]]:
    """业绩预告类型分布，用于前端筛选条与情绪判断。"""
    db = get_db_manager()
    where = "WHERE is_latest = 1" if latest_only else ""
    with db.get_db() as c:
        c.execute(
            f"SELECT forecast_type, COUNT(*) AS n FROM earnings_forecast {where} "
            f"GROUP BY forecast_type ORDER BY n DESC"
        )
        return [dict(r) for r in c.fetchall()]


def get_ipo_calendar(start: Optional[str] = None, end: Optional[str] = None,
                     limit: int = 80) -> List[Dict[str, Any]]:
    """新股日历。不传区间则返回全部（按申购日倒序），供前瞻查看。"""
    db = get_db_manager()
    cond: List[str] = []
    params: List[Any] = []
    if start:
        cond.append("apply_date >= ?"); params.append(start)
    if end:
        cond.append("apply_date <= ?"); params.append(end)
    where = f"WHERE {' AND '.join(cond)}" if cond else ""
    params.append(int(limit))
    with db.get_db() as c:
        c.execute(
            f"SELECT * FROM ipo_calendar {where} ORDER BY apply_date DESC LIMIT ?",
            params,
        )
        return [dict(r) for r in c.fetchall()]


# ---------------------------------------------------------------------------
# 同花顺热榜快照（按交易日自动采集，供历史日期回看）
# ---------------------------------------------------------------------------
def upsert_ths_hotrank(rows: List[Dict[str, Any]]) -> int:
    """批量写入热榜快照（幂等 upsert）。

    rows: {trade_date, list_type, period, category, rank, code, name, market,
           heat, change_pct, rank_chg, popularity_tag, concept_tags(JSON 字符串),
           topic, extra_json(JSON 字符串), collected_at}
    """
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["trade_date"], r["list_type"], r["period"], r.get("category", "stock"),
         int(r.get("rank", 0) or 0),
         r["code"], r.get("name", "") or "", r.get("market", "") or "",
         float(r.get("heat", 0) or 0), float(r.get("change_pct", 0) or 0),
         int(r.get("rank_chg", 0) or 0), (r.get("popularity_tag") or "")[:64],
         r.get("concept_tags", "[]"), (r.get("topic") or "")[:256],
         r.get("extra_json", "[]"), r.get("collected_at", ""))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO ths_hotrank (trade_date, list_type, period, category,
                   rank, code, name, market, heat, change_pct, rank_chg,
                   popularity_tag, concept_tags, topic, extra_json, collected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_date, list_type, period, code) DO UPDATE SET
                   category=excluded.category, rank=excluded.rank,
                   name=excluded.name, market=excluded.market,
                   heat=excluded.heat, change_pct=excluded.change_pct,
                   rank_chg=excluded.rank_chg, popularity_tag=excluded.popularity_tag,
                   concept_tags=excluded.concept_tags, topic=excluded.topic,
                   extra_json=excluded.extra_json, collected_at=excluded.collected_at
            """,
            data,
        )
        return len(data)


def get_ths_hotrank(trade_date: str, list_type: str, period: str,
                    limit: int = 200, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取指定交易日 + 子榜单 + 时间维度的热榜快照（按排名升序）。

    category 为 None 时不限类目（向后兼容）；传入时按类目过滤。
    """
    db = get_db_manager()
    with db.get_db() as c:
        if category:
            c.execute(
                "SELECT * FROM ths_hotrank WHERE trade_date = ? AND list_type = ? "
                "AND period = ? AND category = ? ORDER BY rank ASC LIMIT ?",
                (trade_date, list_type, period, category, int(limit)),
            )
        else:
            c.execute(
                "SELECT * FROM ths_hotrank WHERE trade_date = ? AND list_type = ? "
                "AND period = ? ORDER BY rank ASC LIMIT ?",
                (trade_date, list_type, period, int(limit)),
            )
        return [dict(r) for r in c.fetchall()]


def get_latest_ths_hotrank_date(list_type: str, period: str,
                                category: Optional[str] = None) -> Optional[str]:
    """返回某子榜单最近一次有采集数据的交易日（用于实时获取失败时的回退）。"""
    db = get_db_manager()
    try:
        with db.get_db() as c:
            if category:
                c.execute(
                    "SELECT MAX(trade_date) AS d FROM ths_hotrank "
                    "WHERE list_type = ? AND period = ? AND category = ?",
                    (list_type, period, category),
                )
            else:
                c.execute(
                    "SELECT MAX(trade_date) AS d FROM ths_hotrank "
                    "WHERE list_type = ? AND period = ?",
                    (list_type, period),
                )
            row = c.fetchone()
            return row["d"] if row and row["d"] else None
    except Exception:  # noqa: BLE001
        return None


def get_ths_hotrank_dates() -> Dict[str, Any]:
    """返回所有已采集热榜的交易日列表（倒序）与最新日期。"""
    db = get_db_manager()
    with db.get_db() as c:
        try:
            c.execute(
                "SELECT DISTINCT trade_date FROM ths_hotrank ORDER BY trade_date DESC"
            )
            dates = [r["trade_date"] for r in c.fetchall()]
        except Exception:  # noqa: BLE001
            dates = []
        latest = dates[0] if dates else None
        return {"dates": dates, "latest": latest, "count": len(dates)}


# ---------------------------------------------------------------------------
# 同花顺「涨停聚焦」四模块快照（按交易日自动采集，供历史日期回看）
# ---------------------------------------------------------------------------
def upsert_ths_limitup_pool(rows: List[Dict[str, Any]]) -> int:
    """批量写入涨停 / 炸板 / 跌停池个股（幂等 upsert）。

    rows: {trade_date, pool_type, rank, code, name, price, change_pct, amplitude,
           reason, board, continue_day_cnt, limit_up_time, main_net_amount,
           effective_circulation, turnover_ratio, is_st, is_new, market_code, detail_json}
    """
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["trade_date"], r.get("pool_type", "up"),
         int(r.get("rank", 0) or 0), r["code"], (r.get("name") or "")[:32],
         float(r.get("price", 0) or 0), float(r.get("change_pct", 0) or 0),
         float(r.get("amplitude", 0) or 0), (r.get("reason") or "")[:256],
         (r.get("board") or "")[:16], int(r.get("continue_day_cnt", 0) or 0),
         (r.get("limit_up_time") or "")[:16], float(r.get("main_net_amount", 0) or 0),
         float(r.get("effective_circulation", 0) or 0), float(r.get("turnover_ratio", 0) or 0),
         int(r.get("is_st", 0) or 0), int(r.get("is_new", 0) or 0),
         (r.get("market_code") or "")[:8], r.get("detail_json", "{}"))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO ths_limitup_pool (trade_date, pool_type, rank, code, name,
                   price, change_pct, amplitude, reason, board, continue_day_cnt,
                   limit_up_time, main_net_amount, effective_circulation, turnover_ratio,
                   is_st, is_new, market_code, detail_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_date, pool_type, code) DO UPDATE SET
                   rank=excluded.rank, name=excluded.name, price=excluded.price,
                   change_pct=excluded.change_pct, amplitude=excluded.amplitude,
                   reason=excluded.reason, board=excluded.board,
                   continue_day_cnt=excluded.continue_day_cnt,
                   limit_up_time=excluded.limit_up_time,
                   main_net_amount=excluded.main_net_amount,
                   effective_circulation=excluded.effective_circulation,
                   turnover_ratio=excluded.turnover_ratio, is_st=excluded.is_st,
                   is_new=excluded.is_new, market_code=excluded.market_code,
                   detail_json=excluded.detail_json
            """,
            data,
        )
        return len(data)


def upsert_ths_limitup_ladder(rows: List[Dict[str, Any]]) -> int:
    """批量写入连板天梯（幂等 upsert）。

    rows: {trade_date, height, number, code, name, market_id, continue_num}
    """
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["trade_date"], int(r.get("height", 0) or 0), int(r.get("number", 0) or 0),
         r["code"], (r.get("name") or "")[:32], (r.get("market_id") or "")[:8],
         int(r.get("continue_num", 0) or 0))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO ths_limitup_ladder (trade_date, height, number, code,
                   name, market_id, continue_num)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_date, height, code) DO UPDATE SET
                   number=excluded.number, name=excluded.name,
                   market_id=excluded.market_id, continue_num=excluded.continue_num
            """,
            data,
        )
        return len(data)


def upsert_ths_limitup_wind(rows: List[Dict[str, Any]]) -> int:
    """批量写入风向标股 / 最强风口（幂等 upsert）。

    rows: {trade_date, tab_name, average_change, stock_num, stock_code, stock_name,
           reason, price, change, five_rise, tags, rank}
    """
    if not rows:
        return 0
    db = get_db_manager()
    data = [
        (r["trade_date"], (r.get("tab_name") or "")[:32],
         float(r.get("average_change", 0) or 0), int(r.get("stock_num", 0) or 0),
         r["stock_code"], (r.get("stock_name") or "")[:32],
         (r.get("reason") or "")[:256], float(r.get("price", 0) or 0),
         float(r.get("change", 0) or 0), float(r.get("five_rise", 0) or 0),
         (r.get("tags") or "")[:256], int(r.get("rank", 0) or 0))
        for r in rows
    ]
    with db.get_db() as c:
        c.executemany(
            """INSERT INTO ths_limitup_wind (trade_date, tab_name, average_change,
                   stock_num, stock_code, stock_name, reason, price, change,
                   five_rise, tags, rank)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_date, tab_name, stock_code) DO UPDATE SET
                   average_change=excluded.average_change, stock_num=excluded.stock_num,
                   stock_name=excluded.stock_name, reason=excluded.reason,
                   price=excluded.price, change=excluded.change, five_rise=excluded.five_rise,
                   tags=excluded.tags, rank=excluded.rank
            """,
            data,
        )
        return len(data)


def upsert_ths_limitup_sentiment(row: Dict[str, Any]) -> int:
    """写入某交易日市场情绪总览（幂等 upsert，单日一行）。"""
    if not row:
        return 0
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """INSERT INTO ths_limitup_sentiment (trade_date, turnover_pre, turnover_now,
                   turnover_flag, north_flow, limit_up_pre, limit_up_now, limit_up_flag,
                   rise, fall, deuce, rise_limit, rise_down, hgt_market_status,
                   config_start_date, trade_status, trade_status_ts, collected_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_date) DO UPDATE SET
                   turnover_pre=excluded.turnover_pre, turnover_now=excluded.turnover_now,
                   turnover_flag=excluded.turnover_flag, north_flow=excluded.north_flow,
                   limit_up_pre=excluded.limit_up_pre, limit_up_now=excluded.limit_up_now,
                   limit_up_flag=excluded.limit_up_flag, rise=excluded.rise,
                   fall=excluded.fall, deuce=excluded.deuce, rise_limit=excluded.rise_limit,
                   rise_down=excluded.rise_down, hgt_market_status=excluded.hgt_market_status,
                   config_start_date=excluded.config_start_date,
                   trade_status=excluded.trade_status, trade_status_ts=excluded.trade_status_ts,
                   collected_at=excluded.collected_at
            """,
            (row["trade_date"], float(row.get("turnover_pre", 0) or 0),
             float(row.get("turnover_now", 0) or 0), (row.get("turnover_flag") or "")[:8],
             (row.get("north_flow") or ""), int(row.get("limit_up_pre", 0) or 0),
             int(row.get("limit_up_now", 0) or 0), (row.get("limit_up_flag") or "")[:8],
             int(row.get("rise", 0) or 0), int(row.get("fall", 0) or 0),
             int(row.get("deuce", 0) or 0), int(row.get("rise_limit", 0) or 0),
             int(row.get("rise_down", 0) or 0), (row.get("hgt_market_status") or "")[:32],
             (row.get("config_start_date") or "")[:16], (row.get("trade_status") or "")[:16],
             (row.get("trade_status_ts") or "")[:32], (row.get("collected_at") or "")),
        )
        return 1


def get_ths_limitup_pool(trade_date: str, pool_type: str = "up",
                         limit: int = 500) -> List[Dict[str, Any]]:
    """读取某交易日指定池（up/open/lower）个股列表（按排名升序）。"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT * FROM ths_limitup_pool WHERE trade_date = ? AND pool_type = ? "
            "ORDER BY rank ASC LIMIT ?",
            (trade_date, pool_type, int(limit)),
        )
        return [dict(r) for r in c.fetchall()]


def get_ths_limitup_ladder(trade_date: str) -> List[Dict[str, Any]]:
    """读取某交易日连板天梯（按高度降序）。"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT * FROM ths_limitup_ladder WHERE trade_date = ? "
            "ORDER BY height DESC, code ASC",
            (trade_date,),
        )
        return [dict(r) for r in c.fetchall()]


def get_ths_limitup_wind(trade_date: str,
                         tab_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """读取某交易日风向标股 / 最强风口（按类目 + 排名升序）。"""
    db = get_db_manager()
    with db.get_db() as c:
        if tab_name:
            c.execute(
                "SELECT * FROM ths_limitup_wind WHERE trade_date = ? AND tab_name = ? "
                "ORDER BY rank ASC",
                (trade_date, tab_name),
            )
        else:
            c.execute(
                "SELECT * FROM ths_limitup_wind WHERE trade_date = ? "
                "ORDER BY tab_name, rank ASC",
                (trade_date,),
            )
        return [dict(r) for r in c.fetchall()]


def get_ths_limitup_sentiment(trade_date: str) -> Optional[Dict[str, Any]]:
    """读取某交易日市场情绪总览（单行）。"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT * FROM ths_limitup_sentiment WHERE trade_date = ?",
            (trade_date,),
        )
        row = c.fetchone()
        return dict(row) if row else None


def get_latest_ths_limitup_date() -> Optional[str]:
    """返回四表并集里最近一次有采集数据的交易日（实时失败时的回退锚点）。"""
    db = get_db_manager()
    try:
        with db.get_db() as c:
            c.execute(
                "SELECT MAX(trade_date) AS d FROM ("
                " SELECT MAX(trade_date) AS trade_date FROM ths_limitup_pool UNION ALL"
                " SELECT MAX(trade_date) FROM ths_limitup_ladder UNION ALL"
                " SELECT MAX(trade_date) FROM ths_limitup_wind UNION ALL"
                " SELECT MAX(trade_date) FROM ths_limitup_sentiment)"
            )
            row = c.fetchone()
            return row["d"] if row and row["d"] else None
    except Exception:  # noqa: BLE001
        return None


def get_ths_limitup_dates() -> Dict[str, Any]:
    """返回所有已采集涨停聚焦的交易日列表（倒序）与最新日期。"""
    db = get_db_manager()
    with db.get_db() as c:
        try:
            c.execute(
                "SELECT DISTINCT trade_date FROM ths_limitup_pool ORDER BY trade_date DESC"
            )
            dates = [r["trade_date"] for r in c.fetchall()]
        except Exception:  # noqa: BLE001
            dates = []
        latest = dates[0] if dates else None
        return {"dates": dates, "latest": latest, "count": len(dates)}


def get_sector_heat(trade_date: str, sector_type: str = "concept",
                    min_members: int = 5, order_by: str = "avg_pct",
                    limit: int = 40) -> List[Dict[str, Any]]:
    """板块热度：sector_members × money_flow 聚合。

    产出：成分数、平均涨跌幅、上涨家数、涨停家数（pct_chg >= 9.8 近似）、
          主力净额合计。这是把 97597 行成分映射变成可读结论的关键聚合。

    ⚠️ 涨停判定用 pct_chg >= 9.8 近似而非 join limit_pool：
       limit_pool 依赖 push2ex（限流时可能缺数），而 money_flow 走 datacenter
       主链路始终可用。宁可用近似值，也不让面板因增强链路缺数而空白。
    """
    st = "industry" if sector_type == "industry" else "concept"
    order = {"avg_pct": "avg_pct", "main_net": "main_net",
             "up_limit": "up_limit", "members": "members"}.get(order_by, "avg_pct")
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """SELECT s.sector_name                                    AS sector_name,
                      s.sector_type                                    AS sector_type,
                      COUNT(DISTINCT s.code)                           AS members,
                      ROUND(AVG(m.pct_chg), 2)                         AS avg_pct,
                      SUM(CASE WHEN m.pct_chg > 0 THEN 1 ELSE 0 END)   AS up_cnt,
                      SUM(CASE WHEN m.pct_chg < 0 THEN 1 ELSE 0 END)   AS down_cnt,
                      SUM(CASE WHEN m.pct_chg >= 9.8 THEN 1 ELSE 0 END) AS up_limit,
                      SUM(m.main_net)                                  AS main_net,
                      MAX(m.pct_chg)                                   AS top_pct
               FROM sector_members s
               JOIN money_flow m ON m.code = s.code AND m.trade_date = ?
               WHERE s.sector_type = ?
               GROUP BY s.sector_name
               HAVING members >= ?
               ORDER BY """ + order + """ DESC
               LIMIT ?""",
            (trade_date, st, int(min_members), int(limit)),
        )
        return [dict(r) for r in c.fetchall()]


def get_sector_stocks(sector_name: str, trade_date: str,
                      limit: int = 60) -> List[Dict[str, Any]]:
    """某板块的成分股当日表现（供板块下钻）。"""
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            """SELECT s.code, s.name, m.pct_chg, m.close_price, m.main_net,
                      m.turnover, m.org_participate
               FROM sector_members s
               LEFT JOIN money_flow m ON m.code = s.code AND m.trade_date = ?
               WHERE s.sector_name = ?
               ORDER BY m.pct_chg DESC NULLS LAST
               LIMIT ?""",
            (trade_date, sector_name, int(limit)),
        )
        return [dict(r) for r in c.fetchall()]


def get_stock_profile(code: str, bars: int = 60) -> Dict[str, Any]:
    """个股全息档案：把该标的散落在 9 张事实表中的记录聚合成一份视图。

    这是「数据可见性」的收口 —— 用户输入一个代码，即可看到事实层
    对这只票掌握的全部信息，而不必在多个面板间来回切换。
    """
    code = (code or "").strip()
    if not code:
        return {}
    db = get_db_manager()
    out: Dict[str, Any] = {"code": code}
    with db.get_db() as c:
        c.execute("SELECT * FROM stock_meta WHERE code = ?", (code,))
        row = c.fetchone()
        out["meta"] = dict(row) if row else None

        c.execute("SELECT * FROM money_flow WHERE code = ? "
                  "ORDER BY trade_date DESC LIMIT 1", (code,))
        row = c.fetchone()
        out["money_flow"] = dict(row) if row else None

        c.execute("SELECT * FROM margin_detail WHERE code = ? "
                  "ORDER BY trade_date DESC LIMIT 1", (code,))
        row = c.fetchone()
        out["margin"] = dict(row) if row else None

        c.execute("SELECT * FROM earnings_forecast WHERE code = ? "
                  "ORDER BY notice_date DESC LIMIT 3", (code,))
        out["forecast"] = [dict(r) for r in c.fetchall()]

        c.execute("SELECT * FROM limit_pool WHERE code = ? "
                  "ORDER BY trade_date DESC LIMIT 10", (code,))
        out["limit_records"] = [dict(r) for r in c.fetchall()]

        c.execute("SELECT * FROM billboard WHERE code = ? "
                  "ORDER BY trade_date DESC LIMIT 10", (code,))
        out["billboard"] = [dict(r) for r in c.fetchall()]

        c.execute("SELECT sector_name, sector_type FROM sector_members "
                  "WHERE code = ? ORDER BY sector_type, sector_name", (code,))
        out["sectors"] = [dict(r) for r in c.fetchall()]

        c.execute("SELECT * FROM daily_bar WHERE code = ? AND fq_type = 1 "
                  "ORDER BY trade_date DESC LIMIT ?", (code, int(bars)))
        out["bars"] = list(reversed([dict(r) for r in c.fetchall()]))

        c.execute("SELECT * FROM ipo_calendar WHERE code = ?", (code,))
        row = c.fetchone()
        out["ipo"] = dict(row) if row else None

        # 关联新闻（news_stock_link -> news）
        try:
            c.execute(
                """SELECT n.id, n.title, n.publish_time, n.source
                   FROM news_stock_link l JOIN news n ON n.id = l.news_id
                   WHERE l.code = ? ORDER BY n.publish_time DESC LIMIT 12""",
                (code,),
            )
            out["news"] = [dict(r) for r in c.fetchall()]
        except Exception:  # noqa: BLE001  news 表字段差异时降级
            out["news"] = []
    return out


def search_stock(keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
    """按代码/名称/别名模糊检索标的，供个股档案输入框联想。"""
    kw = (keyword or "").strip()
    if not kw:
        return []
    db = get_db_manager()
    like = f"%{kw}%"
    with db.get_db() as c:
        c.execute(
            """SELECT code, name, board, sw_industry_l1, is_active
               FROM stock_meta
               WHERE code LIKE ? OR name LIKE ? OR alias LIKE ?
               ORDER BY is_active DESC, code LIMIT ?""",
            (like, like, like, int(limit)),
        )
        return [dict(r) for r in c.fetchall()]


# 事实表总览的表清单：(表名, 中文名, 日期列或 None, 主体列或 None)
_OVERVIEW_TABLES = [
    ("stock_meta", "股票名录", None, "code"),
    ("daily_bar", "日线行情", "trade_date", "code"),
    ("money_flow", "资金流", "trade_date", "code"),
    ("margin_detail", "融资融券", "trade_date", "code"),
    ("limit_pool", "涨跌停池", "trade_date", "code"),
    ("billboard", "龙虎榜", "trade_date", "code"),
    ("earnings_forecast", "业绩预告", "notice_date", "code"),
    ("ipo_calendar", "新股日历", "apply_date", "code"),
    ("sector_members", "板块成分", None, "code"),
    ("market_sentiment_daily", "市场温度", "trade_date", None),
    ("news_stock_link", "舆情关联", None, "code"),
]


def get_fact_overview() -> Dict[str, Any]:
    """事实层数据总览：每张表的行数、最新日期、覆盖标的数 + 数据源健康。

    这是运维视角的收口面板 —— 一眼看出哪张表缺数、哪个源熔断。
    """
    db = get_db_manager()
    tables: List[Dict[str, Any]] = []
    with db.get_db() as c:
        for tbl, label, date_col, key_col in _OVERVIEW_TABLES:
            item: Dict[str, Any] = {"table": tbl, "label": label,
                                    "rows": 0, "latest": None, "subjects": None}
            try:
                item["rows"] = c.execute(
                    f'SELECT COUNT(*) FROM "{tbl}"').fetchone()[0]
                if date_col:
                    r = c.execute(
                        f'SELECT MAX({date_col}) FROM "{tbl}"').fetchone()
                    item["latest"] = r[0] if r else None
                if key_col:
                    item["subjects"] = c.execute(
                        f'SELECT COUNT(DISTINCT {key_col}) FROM "{tbl}"').fetchone()[0]
            except Exception as e:  # noqa: BLE001
                item["error"] = str(e)[:80]
            tables.append(item)

        # 股票名录板块分布
        boards: List[Dict[str, Any]] = []
        try:
            boards = [dict(r) for r in c.execute(
                "SELECT COALESCE(NULLIF(board,''),'未归类') AS board, "
                "COUNT(*) AS n, SUM(is_active) AS active "
                "FROM stock_meta GROUP BY board ORDER BY n DESC").fetchall()]
        except Exception:  # noqa: BLE001
            pass

        # 数据源健康
        health: List[Dict[str, Any]] = []
        try:
            health = [dict(r) for r in c.execute(
                "SELECT source_name, total_requests, success_count, failure_count, "
                "consecutive_failures, avg_latency, last_success_ts, last_error, "
                "is_circuit_open FROM source_health "
                "WHERE total_requests > 0 ORDER BY failure_count DESC, "
                "source_name LIMIT 40").fetchall()]
        except Exception:  # noqa: BLE001
            pass

    return {"tables": tables, "boards": boards, "health": health}


def _now() -> str:
    from finfeed.utils.time_utils import now_bj
    return now_bj().strftime("%Y-%m-%d %H:%M:%S")
