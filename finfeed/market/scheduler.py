#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行情后台自动采集调度器

在 Web 进程内常驻一个守护线程，按北京时间「交易日 + 合理时点」自动触发行情采集，
无需用户手动点击。复用 finfeed.market.service 的同步入口，并通过 get_state() 暴露运行状态。

调度策略（北京时间，交易日内生效）：
  - universe : 每个交易日 08:40   刷新股票池与板块成分（盘前）
  - snapshot : 每个交易日 16:10   盘后全市场快照（资金流/宽度/涨跌停/龙虎榜/参考）
  - bars     : 每个交易日 16:40   增量补日线（错峰，受 push2his 限流保护；默认关闭，需 FINFEED_MK_AUTO_BARS=1）

每个任务每日仅执行一次（按自然日去重），网络/解析失败仅记录状态，不影响其它任务与 Web 主线程。
可通过环境变量 FINFEED_MK_AUTO=0 整体关闭；FINFEED_MK_AUTO_BARS=1 开启日线自动补采。
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger("news_monitor")

# 调度表（本地时区；now_bj 返回北京时区 datetime）
SLOTS = {
    "universe": {"h": 8, "m": 40, "default_on": True},
    "snapshot": {"h": 16, "m": 10, "default_on": True},
    "hotrank": {"h": 16, "m": 15, "default_on": True},
    "bars": {"h": 16, "m": 40, "default_on": False},
}

_state_lock = threading.Lock()
_state = {
    "enabled": False,
    "running": False,
    "last_run": {},  # action -> {executed_date, started, finished, status, message}
    "next_run": {},  # action -> "YYYY-MM-DD HH:MM:SS"
}

_enabled_by_default = os.environ.get("FINFEED_MK_AUTO", "1") != "0"
_bars_enabled = os.environ.get("FINFEED_MK_AUTO_BARS", "0") == "1"


def _now_bj():
    from finfeed.utils.time_utils import now_bj

    return now_bj()


def _is_trading_day(dt: datetime) -> bool:
    # 周一至周五为交易日（节假日未穷举；休市日东方财富接口返回空，安全降级）
    return dt.weekday() < 5


def _slot_enabled(action: str) -> bool:
    if action == "bars":
        return _bars_enabled
    return SLOTS[action]["default_on"]


def _next_slot_str(action: str, now: datetime) -> str:
    slot = SLOTS[action]
    today = now.replace(hour=slot["h"], minute=slot["m"], second=0, microsecond=0)
    if now <= today:
        target = today
    else:
        target = today + timedelta(days=1)
    return target.strftime("%Y-%m-%d %H:%M:%S")


def _maybe_run(action: str, now: datetime) -> bool:
    if not _slot_enabled(action):
        return False
    if not _is_trading_day(now):
        return False
    slot = SLOTS[action]
    if now.hour < slot["h"] or (now.hour == slot["h"] and now.minute < slot["m"]):
        return False
    today = now.strftime("%Y-%m-%d")
    with _state_lock:
        last = _state["last_run"].get(action, {})
        if last.get("executed_date") == today:
            return False  # 今日已执行，避免重复
    return True


def _empty_check(action: str):
    """按任务类型判定采集结果是否为空（空数据视为一次失败）。"""

    def check(res):
        if res is None:
            return True
        if action == "universe":
            sm = res.get("stock_meta")
            ac = res.get("active")
            return (sm in (None, "", "?", 0, "0")) and (ac in (None, "", "?", 0, "0"))
        if action == "snapshot":
            return not res.get("trade_date")
        if action == "hotrank":
            return not res.get("saved")
        if action == "bars":
            saved = res.get("saved", res.get("total"))
            try:
                return int(saved or 0) <= 0
            except (TypeError, ValueError):
                return False
        return False

    return check


def _run_action(action: str, today: str):
    from finfeed.market import alerting as mk_alerting
    from finfeed.market import service as svc

    task = f"market:{action}"
    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _state_lock:
        _state["last_run"][action] = {
            "executed_date": today,
            "started": started,
            "status": "running",
            "message": f"自动采集 {action} 进行中…",
        }
    try:
        if action == "universe":
            res = mk_alerting.with_retry(
                task, lambda: svc.run_universe_sync(),
                max_retries=3, backoff_base=2.0, timeout=180,
                is_empty=_empty_check(action),
            )
            msg = f"完成（名录 {res.get('stock_meta', '?')} / 在市 {res.get('active', '?')}）"
        elif action == "snapshot":
            res = mk_alerting.with_retry(
                task, lambda: svc.run_daily_snapshot_sync(),
                max_retries=3, backoff_base=2.0, timeout=300,
                is_empty=_empty_check(action),
            )
            msg = f"完成（交易日 {res.get('trade_date', today)}）"
        elif action == "hotrank":
            res = mk_alerting.with_retry(
                task, lambda: svc.collect_hotrank_sync(),
                max_retries=3, backoff_base=2.0, timeout=300,
                is_empty=_empty_check(action),
            )
            msg = f"完成（采集 {res.get('saved', 0)} 条 / {res.get('trade_date', today)}）"
        elif action == "bars":
            res = mk_alerting.with_retry(
                task, lambda: svc.collect_bars_sync(bars=5),
                max_retries=2, backoff_base=2.0, timeout=600,
                is_empty=_empty_check(action),
            )
            msg = f"完成（{res.get('saved', res.get('total', '已同步'))} 条）"
        else:
            return
        status = "done"
    except Exception as e:  # noqa: BLE001
        msg = f"失败：{e}"
        status = "error"
        logger.error("行情自动采集 %s 失败: %s", action, e, exc_info=True)
    finished = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _state_lock:
        _state["last_run"][action] = {
            "executed_date": today,
            "started": started,
            "finished": finished,
            "status": status,
            "message": msg,
        }


def _worker(action: str, today: str):
    try:
        _run_action(action, today)
    except Exception as e:  # noqa: BLE001
        logger.error("行情自动采集线程异常 %s: %s", action, e, exc_info=True)


def _loop():
    logger.info(
        "行情自动采集调度器已启动（universe 08:40 / snapshot 16:10 / bars 16:40，交易日内各一次）"
    )
    while _state["enabled"]:
        try:
            now = _now_bj()
            with _state_lock:
                for action in SLOTS:
                    _state["next_run"][action] = (
                        _next_slot_str(action, now) if _slot_enabled(action) else None
                    )
            for action in SLOTS:
                if _maybe_run(action, now):
                    today = now.strftime("%Y-%m-%d")
                    t = threading.Thread(
                        target=_worker, args=(action, today), daemon=True, name=f"mk-auto-{action}"
                    )
                    t.start()
        except Exception as e:  # noqa: BLE001
            logger.error("行情自动采集调度循环异常: %s", e, exc_info=True)
        # 每分钟检查一次，保证到点即触发；shutdown 时最长 1s 内退出
        for _ in range(60):
            if not _state["enabled"]:
                break
            time.sleep(1)


def start():
    """启动调度循环（已启动则幂等返回）。"""
    with _state_lock:
        if _state["enabled"]:
            return
        _state["enabled"] = True
    t = threading.Thread(target=_loop, daemon=True, name="mk-autocollect")
    t.start()


def stop():
    """停止调度循环（已停止则幂等）。"""
    with _state_lock:
        _state["enabled"] = False


def get_state() -> dict:
    with _state_lock:
        return {
            "enabled": _state["enabled"],
            "last_run": dict(_state["last_run"]),
            "next_run": dict(_state["next_run"]),
            "enabled_by_default": _enabled_by_default,
            "bars_enabled": _bars_enabled,
        }


def maybe_autostart():
    """进程启动时按默认开关决定是否自动开启（可被 FINFEED_MK_AUTO=0 关闭）。"""
    if _enabled_by_default:
        start()
