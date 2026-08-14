#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集失败告警模块

为数据采集任务（行情 universe / snapshot / bars、日历同步、新闻抓取等）提供统一的
失败监控与告警能力：

  - **失败检测**：覆盖三类失败 —— 异常（exception）、超时（timeout）、空数据（empty）。
  - **重试逻辑**：``with_retry`` 提供指数退避重试，单次任务内部自愈；超时通过线程 Future 实现。
  - **失败计数**：按任务名累计失败次数，成功一次即清零（连续失败一目了然）。
  - **防重复告警**：相同 (任务, 类型) 签名在冷却窗口内只真正通知一次，避免告警风暴；
    最后一次重试（exhausted）强制通知一次，确保「彻底失败」不会错过。
  - **通知器**：默认 ``LogNotifier``（写日志）；可选 ``WebhookNotifier``（环境变量
    ``FINFEED_ALERT_WEBHOOK`` 配置）。另可通过 ``on_alert_callback`` 把告警实时推给
    WebSocket / SSE 等通道。
  - **内存环形缓冲**：最近告警通过 ``get_recent`` / ``get_stats`` 暴露给 API 与前端。

设计原则：本模块绝不因告警逻辑本身抛出异常而中断采集；所有通知/记录都在锁外执行，
且全程 try/except 兜底，满足「健壮、容错完善」要求。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("news_monitor")

# 失败类型常量
KIND_EXCEPTION = "exception"   # 代码异常
KIND_TIMEOUT = "timeout"      # 执行超时
KIND_EMPTY = "empty"          # 返回空数据（疑似采集失败）
KIND_EXHAUSTED = "exhausted"  # 重试耗尽仍失败

# 默认告警冷却窗口（秒）：同一签名在该窗口内只通知一次
DEFAULT_COOLDOWN = 3600
# 内存中保留的最近告警条数
RECENT_MAX = 300


class AlertError(Exception):
    """告警模块内部错误（通常不会抛出到业务层）。"""


class EmptyDataError(AlertError):
    """采集返回空数据，视为一次失败。"""


class Notifier:
    """通知器基类。子类实现 ``notify``。"""

    name = "base"

    def notify(self, record: Dict[str, Any]) -> None:  # pragma: no cover - 抽象
        raise NotImplementedError


class LogNotifier(Notifier):
    """默认通知器：把告警写入日志（ERROR 级别）。"""

    name = "log"

    def notify(self, record: Dict[str, Any]) -> None:
        try:
            msg = (
                f"[采集告警] task={record['task']} kind={record['kind']} "
                f"count={record['count']} ts={record['ts']} :: {record['error']}"
            )
            logger.error(msg)
        except Exception:  # noqa: BLE001
            # 通知器本身失败绝不能影响业务
            pass


class WebhookNotifier(Notifier):
    """Webhook 通知器：把告警 POST 到配置的 URL（环境变量 FINFEED_ALERT_WEBHOOK）。

    失败静默降级（不抛异常、不影响其它逻辑）。
    """

    name = "webhook"

    def __init__(self, url: str, timeout: float = 5.0):
        self.url = url
        self.timeout = timeout

    def notify(self, record: Dict[str, Any]) -> None:
        try:
            import urllib.request

            data = json.dumps(record, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                if resp.status >= 400:
                    logger.warning(f"告警 Webhook 返回非 2xx: {resp.status}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"告警 Webhook 推送失败（已忽略）: {e}")


class FailureAlertManager:
    """采集失败告警管理器（线程安全单例）。"""

    def __init__(self, cooldown: int = DEFAULT_COOLDOWN):
        self._lock = threading.RLock()
        self.cooldown = cooldown
        self._counters: Dict[str, int] = {}                 # task -> 累计失败次数
        self._last_alert_ts: Dict[str, float] = {}          # signature -> 上次真正通知时间
        self._recent: deque = deque(maxlen=RECENT_MAX)      # 最近告警记录
        self._notifiers: List[Notifier] = [LogNotifier()]
        wh = ""
        try:
            import os

            wh = os.environ.get("FINFEED_ALERT_WEBHOOK", "").strip()
        except Exception:  # noqa: BLE001
            wh = ""
        if wh:
            self._notifiers.append(WebhookNotifier(wh))
            logger.info(f"采集失败告警已挂载 Webhook 通知器: {wh}")
        # 实时推送钩子（如推给 WebSocket 服务）；默认为空操作
        self.on_alert_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def record_failure(
        self,
        task: str,
        error: str,
        kind: str = KIND_EXCEPTION,
        signature: Optional[str] = None,
        force_alert: bool = False,
    ) -> int:
        """记录一次失败。

        返回该任务当前的累计失败次数。相同 signature 在冷却窗口内只触发一次真正
        通知（写入 recent + 调用 notifiers + 回调），避免告警风暴；``force_alert``
        可强制通知一次（用于重试耗尽的最终告警）。
        """
        sig = signature or f"{task}:{kind}"
        now = time.time()
        with self._lock:
            self._counters[task] = self._counters.get(task, 0) + 1
            count = self._counters[task]
            last = self._last_alert_ts.get(sig, 0.0)
            should_alert = bool(force_alert) or (now - last) >= self.cooldown
            rec = None
            if should_alert:
                self._last_alert_ts[sig] = now
                rec = {
                    "task": task,
                    "kind": kind,
                    "signature": sig,
                    "error": (error or "")[:500],
                    "count": count,
                    "ts": now,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                }
                self._recent.append(rec)
        if should_alert and rec is not None:
            self._dispatch(rec)
        return count

    def record_success(self, task: str) -> None:
        """记录一次成功：清空该任务的失败计数（连续失败归零）。"""
        with self._lock:
            if self._counters.get(task):
                self._counters[task] = 0
        try:
            logger.info(f"采集任务恢复成功，失败计数清零: {task}")
        except Exception:  # noqa: BLE001
            pass

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._recent)
        items.reverse()
        return items[: max(1, min(limit, RECENT_MAX))]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            total = sum(1 for v in counters.values() if v > 0)
        return {
            "tasks": counters,
            "active_alerts": total,
            "recent_count": len(self._recent),
            "cooldown": self.cooldown,
            "notifiers": [n.name for n in self._notifiers],
            "callback": self.on_alert_callback is not None,
        }

    def reset(self, task: Optional[str] = None) -> None:
        with self._lock:
            if task:
                self._counters.pop(task, None)
                # 仅清理该 task 相关的签名冷却，避免误伤其它任务
                for k in [k for k in self._last_alert_ts if k.startswith(f"{task}:")]:
                    self._last_alert_ts.pop(k, None)
            else:
                self._counters.clear()
                self._last_alert_ts.clear()

    # ------------------------------------------------------------------
    # 重试包装
    # ------------------------------------------------------------------
    def with_retry(
        self,
        task: str,
        fn: Callable[[], Any],
        *,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        timeout: Optional[float] = None,
        is_empty: Optional[Callable[[Any], bool]] = None,
        kind: str = KIND_EXCEPTION,
    ) -> Any:
        """带重试地执行 ``fn``，集成失败检测与告警。

        - 异常 / 超时 / 空数据都视为一次失败（空数据抛 ``EmptyDataError``）。
        - 单次失败后按 ``backoff_base * 2**(attempt-1)`` 指数退避重试。
        - 每次失败都累加计數；同签名冷却窗口内只通知一次；最后一次重试失败强制通知。
        - 全部耗尽后抛出最后一次异常。
        """
        last_err: Optional[BaseException] = None
        for attempt in range(1, max_retries + 1):
            try:
                result = self._call(fn, timeout)
                if is_empty and is_empty(result):
                    raise EmptyDataError(f"{task} 返回空数据（疑似采集失败）")
                # 成功：清零连续失败计数
                self.record_success(task)
                return result
            except Exception as e:  # noqa: BLE001
                last_err = e
                ek = KIND_TIMEOUT if isinstance(e, FuturesTimeout) else (
                    KIND_EMPTY if isinstance(e, EmptyDataError) else kind
                )
                is_last = attempt >= max_retries
                self.record_failure(
                    task,
                    error=f"{type(e).__name__}: {e}",
                    kind=ek,
                    signature=f"{task}:{ek}",
                    force_alert=is_last,
                )
                if is_last:
                    break
                # 指数退避
                sleep_s = backoff_base * (2 ** (attempt - 1))
                time.sleep(min(sleep_s, 30))
        # 重试耗尽
        raise (last_err or AlertError(f"{task} 重试耗尽"))

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    def _call(self, fn: Callable[[], Any], timeout: Optional[float]) -> Any:
        if timeout and timeout > 0:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(fn)
                try:
                    return fut.result(timeout=timeout)
                except FuturesTimeout:
                    fut.cancel()
                    raise TimeoutError(f"执行超时（{timeout}s）")
        return fn()

    def _dispatch(self, rec: Dict[str, Any]) -> None:
        """在锁外执行通知与回调，避免阻塞采集线程。"""
        try:
            for n in self._notifiers:
                try:
                    n.notify(rec)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        cb = self.on_alert_callback
        if cb is not None:
            try:
                cb(rec)
            except Exception:  # noqa: BLE001
                pass


# 模块级单例（全局共享失败计数与告警缓冲）
manager = FailureAlertManager()


def get_manager() -> FailureAlertManager:
    return manager


# 便捷别名（供其它模块一行调用）
def record_failure(task: str, error: str, kind: str = KIND_EXCEPTION, **kw) -> int:
    return manager.record_failure(task, error, kind, **kw)


def record_success(task: str) -> None:
    manager.record_success(task)


def with_retry(task: str, fn: Callable[[], Any], **kw) -> Any:
    return manager.with_retry(task, fn, **kw)


def get_recent(limit: int = 50) -> List[Dict[str, Any]]:
    return manager.get_recent(limit)


def get_stats() -> Dict[str, Any]:
    return manager.get_stats()
