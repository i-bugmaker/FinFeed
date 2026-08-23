"""Market-data application services (framework-independent use cases).

将行情查询/采集用例从传输层（``finfeed.ui.web_fastapi.app``）下沉到应用层，
使 FastAPI 路由（``routers/market.py``）保持纯传输边界：
- 数据查询用例（sentiment/limitup/billboard/moneyflow/margin/…）→ :meth:`MarketService.dispatch`
- 采集运维动作（快照/K线/股票池/情绪校准）→ :meth:`MarketService.run_action`
- 指数 K 线 / 分时（内存 TTL + SQLite kline_cache）→ :meth:`MarketService.get_chart_data`
- 数据可用日期 → :meth:`MarketService.get_dates`

采集动作的底层依赖（market.service / 情绪校准 / 线程执行）可注入，
默认实现与 legacy（``finfeed.ui.web.server``）行为完全一致。
"""

from __future__ import annotations

import logging
import threading as _threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Dict

from finfeed.market import alerting as market_alerting
from finfeed.market import scheduler as market_scheduler
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")


def first_query_value(query: Mapping[str, list[str]], key: str, default: str = "") -> str:
    """Read a normalized multi-value query map without index errors."""
    values = query.get(key)
    return values[0] if values else default


def bounded_int(
    query: Mapping[str, list[str]], key: str, default: int, maximum: int = 500, minimum: int = 1
) -> int:
    """Parse and clamp a positive numeric market parameter."""
    try:
        return max(minimum, min(int(first_query_value(query, key, str(default))), maximum))
    except (TypeError, ValueError):
        return default


# ----------------------------------------------------------------------
# 采集动作依赖的默认实现（与 legacy _get_mk_service/_run_in_thread/_mk_calibrate 等价）
# ----------------------------------------------------------------------
def _default_get_mk_service():
    """延迟导入 market.service，Web 启动时不触发东方财富连接。"""
    from finfeed.market import service as _svc
    return _svc


def _default_mk_calibrate():
    """情绪校准（延迟导入 crossref）。"""
    from finfeed.analysis import crossref
    return crossref.calibrate_sentiment()


def _default_run_in_thread(fn: Callable[[], Any], timeout: int = 0) -> Any:
    """在当前线程同步执行 fn()；调用方应将其放入 Thread 以实现后台执行。"""
    return fn()


def _strip_fetched(rows_list):
    """去掉内部字段 fetched_at，仅返回前端需要的行情字段。"""
    return [{k: v for k, v in r.items() if k != "fetched_at"} for r in rows_list]


def _ok(rows_list):
    return {"rows": rows_list or [], "reason": "ok" if rows_list else "empty"}


def _last_n(rows_list, limit):
    """取最近 limit 根（保持升序）；limit 为空则原样返回。"""
    if not rows_list or not limit:
        return rows_list or []
    return rows_list[-int(limit):]


class MarketService:
    """市场行情应用服务：查询用例 + 采集运维动作 + 图表数据。

    K 线/分时图表缓存（内存 TTL + SQLite kline_cache）状态收归本类，
    与传输层解耦；不依赖任何 HTTP 框架。
    """

    # 分时内存缓存 TTL（秒）
    _KLINE_CACHE_TTL = 300.0
    # K 线周期 -> 缓存 TTL（秒）：日K 30min / 周K 1h / 月K 3h / 季K 6h / 年K 12h
    _KLINE_TTL = {101: 1800, 102: 3600, 103: 10800, 104: 21600, 105: 43200}
    # K 线周期 -> 单次拉取窗口（根数，与前端「全部」lmt 对齐）
    _KLINE_WINDOW = {101: 1500, 102: 520, 103: 240, 104: 80, 105: 30}

    def __init__(
        self,
        *,
        get_mk_service: Callable[[], Any] | None = None,
        run_in_thread: Callable[[Callable[[], Any], int], Any] | None = None,
        mk_calibrate: Callable[[], Any] | None = None,
    ) -> None:
        self._get_mk_service = get_mk_service or _default_get_mk_service
        self._run_in_thread = run_in_thread or _default_run_in_thread
        self._mk_calibrate = mk_calibrate or _default_mk_calibrate
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._kline_cache: Dict[tuple, tuple] = {}

    # ------------------------------------------------------------------
    # 数据可用日期
    # ------------------------------------------------------------------
    def get_dates(self, fallback_date: str) -> dict:
        """各行情表的最新交易日期与默认日期（与 legacy._market_dates 对齐）。"""
        from finfeed.storage.database import get_db
        out: Dict[str, Any] = {"billboard": None, "limit_pool": None, "sentiment": None}
        with get_db() as c:
            for tbl, key, cond in (
                ("billboard", "billboard", ""),
                ("limit_pool", "limit_pool", ""),
                ("market_sentiment_daily", "sentiment", "WHERE (breadth > 0 OR up_limit > 0 OR down_limit > 0)"),
                ("money_flow", "money_flow", ""),
                ("margin_detail", "margin_detail", ""),
                ("daily_bar", "daily_bar", ""),
            ):
                try:
                    c.execute(f"SELECT MAX(trade_date) AS d FROM {tbl} {cond}")
                    row = c.fetchone()
                    out[key] = row["d"] if row and row["d"] else None
                except Exception:
                    out[key] = None
            for tbl, key, col in (
                ("earnings_forecast", "forecast", "notice_date"),
                ("ipo_calendar", "ipo", "apply_date"),
            ):
                try:
                    c.execute(f"SELECT MAX({col}) AS d FROM {tbl}")
                    row = c.fetchone()
                    out[key] = row["d"] if row and row["d"] else None
                except Exception:
                    out[key] = None
        table_dates = [d for d in (out["billboard"], out["limit_pool"]) if d]
        if table_dates:
            out["default_date"] = max(table_dates)
        else:
            sent = out.get("sentiment")
            out["default_date"] = sent or fallback_date
        out["has_billboard"] = out["billboard"] is not None
        out["has_limit_pool"] = out["limit_pool"] is not None
        return out

    # ------------------------------------------------------------------
    # 采集运维动作（快照 / K线 / 股票池 / 情绪校准）
    # ------------------------------------------------------------------
    def run_action(self, q: Mapping[str, list[str]]) -> dict:
        """启动/查询后台采集任务（与 legacy._serve_market_action 对齐）。"""
        def gv(key, default):
            v = q.get(key)
            return v[0] if v else default
        action = (gv("action", "") or "").strip().lower()
        date = gv("date", None)

        if action == "status":
            tasks = {k: {"status": v["status"], "message": v.get("message", ""), "started": v.get("started", ""), "result": v.get("result")}
                     for k, v in self._tasks.items()}
            return {"success": True, "data": tasks}

        if action == "autocollect":
            enable = gv("enable", "1") not in ("0", "false", "no")
            if enable:
                market_scheduler.start()
            else:
                market_scheduler.stop()
            return {"success": True, "data": market_scheduler.get_state()}

        svc = self._get_mk_service()
        ACTION_MAP = {
            "snapshot": ("采集行情快照", lambda: self._run_in_thread(lambda d=date: svc.run_daily_snapshot_sync(d))),
            "bars": ("采集K线数据", lambda: self._run_in_thread(lambda d=date: svc.collect_bars_sync(d))),
            "universe": ("初始化股票池", lambda: self._run_in_thread(lambda: svc.run_universe_sync())),
            "calibrate": ("校准情绪模型", lambda: self._run_in_thread(lambda: self._mk_calibrate())),
        }
        if action not in ACTION_MAP:
            return {"success": False, "error": f"未知操作: {action}，可选: {', '.join(ACTION_MAP)}"}
        existing = self._tasks.get(action)
        if existing and existing["status"] == "running":
            return {"success": False, "error": f"「{ACTION_MAP[action][0]}」正在执行中，请等待完成"}
        label = ACTION_MAP[action][0]
        task_id = f"{action}_{int(time.time())}"
        self._tasks[action] = {"status": "running", "message": f"⏳ {label} 执行中…", "started": datetime.now().strftime("%H:%M:%S"), "result": None}

        def _worker():
            try:
                result = ACTION_MAP[action][1]()
                self._tasks[action]["status"] = "done"
                self._tasks[action]["message"] = f"✅ {label} 完成"
                self._tasks[action]["result"] = result
            except Exception as exc:
                self._tasks[action]["status"] = "error"
                self._tasks[action]["message"] = f"❌ {label} 失败: {exc}"
                self._tasks[action]["result"] = str(exc)
                logger.error("Market action '%s' failed: %s", action, exc, exc_info=True)
        t = _threading.Thread(target=_worker, daemon=True, name=f"mk-{action}")
        t.start()
        return {"success": True, "data": {"task_id": task_id, "action": action, "label": label, "status": "running", "message": f"已启动「{label}，后台执行中"}}

    # ------------------------------------------------------------------
    # 指数 K 线 / 分时
    # 分时（trends）：内存 TTL 缓存（300s），日内瞬态数据不入库。
    # K 线（101 日 / 102 周 / 103 月 / 104 季 / 105 年）：本地 SQLite kline_cache
    #   优先 + TTL 定期刷新。每个 (code, klt) 在 TTL 窗口内至多触发一次东财
    #   push2his 请求，其余请求全部命中本地库，规避 600s 冷却限流。
    # ------------------------------------------------------------------
    async def get_chart_data(self, code, chart_type, klt, ndays, lmt, start, end) -> dict:
        """返回 {rows: [...], reason: 'ok'|'empty'|'rate_limited'|'error', error?: str}。

        分时走内存 TTL 缓存；K 线走本地 SQLite kline_cache：
        - TTL 内新鲜 → 直接读库返回（不触网）；
        - 过期/无缓存 → 若处于限流冷却则不触网，回退旧缓存；
        - 否则发一次东财请求（取「全部」窗口）写入缓存后返回。
        """
        from finfeed.market import kline as _mk_kline
        from finfeed.market import store as _mk_store
        from finfeed.market.client import RateLimited, cooldown_remaining

        now = time.time()

        # ---- 分时：内存 TTL 缓存（与旧行为一致）----
        if chart_type == "trends":
            key = (code, chart_type, klt, ndays, lmt, start, end)
            cached = self._kline_cache.get(key)
            if cached and (now - cached[0]) < self._KLINE_CACHE_TTL:
                return cached[1]
            try:
                result = _ok(await _mk_kline.fetch_trends(code, ndays=ndays))
            except RateLimited:
                logger.warning("分时获取被限流：%s", code)
                return {"rows": [], "reason": "rate_limited"}
            except Exception as e:  # noqa: BLE001
                logger.warning("分时获取失败 %s: %s", code, e)
                return {"rows": [], "reason": "error", "error": str(e)[:200]}
            if result["reason"] == "ok":
                self._kline_cache[key] = (now, result)
            return result

        # ---- K 线：本地优先 + TTL 刷新 ----
        # 日线且有起止区间时优先读 daily_bar（盘后快照已入库的标的）
        if klt == 101 and start and end:
            db_rows = _mk_store.get_daily_bar(code, start, end)
            if db_rows:
                return _ok(db_rows)

        cached_rows = _mk_store.get_cached_kline(code, klt, start, end)
        if cached_rows:
            newest_fetched = max(r["fetched_at"] for r in cached_rows)
            try:
                fetched_dt = datetime.strptime(newest_fetched, "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                fetched_dt = None
            ttl = self._KLINE_TTL.get(klt, 1800)
            if fetched_dt is not None and (now_bj() - fetched_dt).total_seconds() < ttl:
                return _ok(_strip_fetched(_last_n(cached_rows, lmt)))

        # 过期 / 无缓存：限流冷却期内不触网，回退旧缓存（旧数据优于空/限流提示）
        if cooldown_remaining("em_push2his") > 0:
            if cached_rows:
                return _ok(_strip_fetched(_last_n(cached_rows, lmt)))
            return {"rows": [], "reason": "rate_limited"}

        try:
            first_date = cached_rows[0]["trade_date"] if cached_rows else None
            if start and first_date and start < first_date:
                # 自定义历史区间早于缓存最早日期：区间模式补拉并合并进缓存
                bars = await _mk_kline.fetch_daily_bar(
                    code, end_date=end or "20500101", beg=start, klt=klt
                )
            else:
                # 常规刷新：一次取「全部」窗口，覆盖所有快捷区间
                bars = await _mk_kline.fetch_daily_bar(
                    code, end_date=end, limit=self._KLINE_WINDOW.get(klt, 1500), klt=klt
                )
            if bars:
                _mk_store.upsert_kline_cache([dict(b, code=code) for b in bars], klt)
            rows = _mk_store.get_cached_kline(code, klt, start, end)
            return _ok(_strip_fetched(_last_n(rows, lmt)))
        except RateLimited:
            logger.warning("K线获取被限流：%s", code)
            if cached_rows:
                return _ok(_strip_fetched(_last_n(cached_rows, lmt)))
            return {"rows": [], "reason": "rate_limited"}
        except Exception as e:  # noqa: BLE001
            logger.warning("K线获取失败 %s: %s", code, e)
            rows = _last_n(cached_rows, lmt) if cached_rows else []
            return {"rows": _strip_fetched(rows), "reason": "error", "error": str(e)[:200]}

    # ------------------------------------------------------------------
    # 行情数据用例分发（action 之外的查询子用例）
    # ------------------------------------------------------------------
    async def dispatch(self, sub: str, q: Mapping[str, list[str]], date: str) -> Any:
        """执行单个行情查询用例并返回数据（不含 success 包装；未知用例返回 error dict）。"""
        def _int(key: str, default: int, cap: int = 500) -> int:
            return bounded_int(q, key, default, maximum=cap)

        from finfeed.market import alerts as mk_alerts
        from finfeed.market import store as mk_store
        from finfeed.storage import sentiment_store as ss

        if sub == "sentiment":
            data = ss.get_market_sentiment(date) or {}
        elif sub == "dates":
            data = self.get_dates(date)
        elif sub == "limitup":
            data = mk_store.get_limit_pool(date, "up")
        elif sub == "limitdown":
            data = mk_store.get_limit_pool(date, "down")
        elif sub == "limitbroken":
            data = mk_store.get_limit_pool(date, "broken")
        elif sub == "billboard":
            data = mk_store.get_billboard(date)
        elif sub == "alerts":
            data = mk_alerts.regime_summary(date)
        elif sub == "moneyflow":
            d = mk_store.latest_date("money_flow") or date
            data = {
                "trade_date": d,
                "summary": mk_store.get_money_flow_summary(d),
                "inflow": mk_store.get_money_flow(d, "in", first_query_value(q, "order", "main_net"), bounded_int(q, "limit", 40)),
                "outflow": mk_store.get_money_flow(d, "out", first_query_value(q, "order", "main_net"), bounded_int(q, "limit", 40)),
            }
        elif sub == "margin":
            d = mk_store.latest_date("margin_detail") or date
            order = q.get("order", ["fin_net"])[0]
            data = {
                "trade_date": d,
                "summary": mk_store.get_margin_summary(d),
                "top": mk_store.get_margin_rank(d, order, True, _int("limit", 40)),
                "bottom": mk_store.get_margin_rank(d, order, False, _int("limit", 40)),
            }
        elif sub == "forecast":
            ftype = (q.get("type", [""])[0] or "").strip() or None
            data = {
                "stats": mk_store.get_forecast_type_stats(),
                "rows": mk_store.get_earnings_forecast(ftype=ftype, order_by=q.get("order", ["increase_high"])[0], limit=_int("limit", 80)),
            }
        elif sub == "ipo":
            data = mk_store.get_ipo_calendar(q.get("start", [None])[0], q.get("end", [None])[0], _int("limit", 80))
        elif sub == "sectors":
            d = mk_store.latest_date("money_flow") or date
            stype = q.get("stype", ["concept"])[0]
            data = {
                "trade_date": d,
                "sector_type": stype,
                "rows": mk_store.get_sector_heat(d, stype, min_members=_int("min_members", 5, 100), order_by=q.get("order", ["avg_pct"])[0], limit=_int("limit", 40)),
            }
        elif sub == "sectorstocks":
            d = mk_store.latest_date("money_flow") or date
            data = mk_store.get_sector_stocks(q.get("sector", [""])[0], d, _int("limit", 60))
        elif sub == "profile":
            code = q.get("code", [""])[0]
            data = mk_store.get_stock_profile(code, _int("bars", 120))
        elif sub == "search":
            data = mk_store.search_stock(q.get("kw", [""])[0], _int("limit", 20, 50))
        elif sub == "autostatus":
            data = market_scheduler.get_state()
        elif sub == "alertlog":
            data = {
                "recent": market_alerting.get_recent(limit=_int("limit", 50)),
                "stats": market_alerting.get_stats(),
            }
        elif sub == "hotrank":
            from finfeed.market.ths_hotrank import fetch_hotrank
            category = (q.get("category", ["stock"])[0] or "stock").strip()
            list_type = (q.get("list", ["normal"])[0] or "normal").strip()
            period = (q.get("period", ["hour"])[0] or "hour").strip()
            date = (q.get("date", [None])[0]) or None
            data = await fetch_hotrank(
                list_type, period, _int("limit", 100, 200), date, category=category
            )
        elif sub == "hotrank_dates":
            from finfeed.market import store as mk_store
            data = mk_store.get_ths_hotrank_dates()
        elif sub == "thslimitup":
            from finfeed.market import ths_limitup
            section = (q.get("section", ["all"])[0] or "all").strip()
            date = (q.get("date", [None])[0]) or None
            if section == "all":
                data = await ths_limitup.fetch_limitup_focus(date, sections="all")
            elif section == "intensity":
                data = await ths_limitup.fetch_limit_up_intensity(date)
            elif section == "ladder":
                data = await ths_limitup.fetch_board_ladder(date)
            elif section == "wind":
                data = await ths_limitup.fetch_strong_wind(date)
            elif section == "sentiment":
                data = await ths_limitup.fetch_market_sentiment(date)
            else:
                data = {"error": f"unknown limitup section: {section}"}
        elif sub == "thslimitup_dates":
            from finfeed.market import store as mk_store
            data = mk_store.get_ths_limitup_dates()
        elif sub == "overview":
            data = mk_store.get_fact_overview()
        elif sub == "kline":
            code = q.get("code", [""])[0]
            if not code:
                data = []
            else:
                chart_type = (q.get("type", ["kline"])[0] or "kline").strip()
                klt = _int("klt", 101, 105)
                ndays = _int("ndays", 1, 10)
                lmt = _int("lmt", 250, 2000)
                start = q.get("start", [None])[0]
                end = q.get("end", [None])[0]
                data = await self.get_chart_data(code, chart_type, klt, ndays, lmt, start, end)
        else:
            data = {"error": f"unknown market action: {sub}"}
        return data
