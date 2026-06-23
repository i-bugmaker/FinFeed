#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据源健康度监控与断路器

功能：
- 跟踪每个源的成功率、延迟、连续失败次数
- 断路器模式：连续失败 N 次后暂时熔断，避免浪费资源
- 状态持久化到数据库
"""

import time
from typing import Optional

from config.settings import (
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_RECOVERY_TIME,
)
from storage.models import SourceHealth
from storage.database import get_db


class HealthMonitor:
    """源健康度监控器"""

    def __init__(self):
        self._health: dict[str, SourceHealth] = {}
        self._loaded = False

    def load_from_db(self):
        """从数据库加载健康状态"""
        if self._loaded:
            return
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute("SELECT * FROM source_health")
                for row in c.fetchall():
                    sh = SourceHealth(
                        source_name=row["source_name"],
                        total_requests=row["total_requests"] or 0,
                        success_count=row["success_count"] or 0,
                        failure_count=row["failure_count"] or 0,
                        consecutive_failures=row["consecutive_failures"] or 0,
                        avg_latency=row["avg_latency"] or 0.0,
                        last_success_ts=row["last_success_ts"] or 0,
                        last_failure_ts=row["last_failure_ts"] or 0,
                        last_error=row["last_error"] or "",
                        is_circuit_open=bool(row["is_circuit_open"]),
                        circuit_open_ts=row["circuit_open_ts"] or 0,
                    )
                    self._health[sh.source_name] = sh
        except Exception:
            pass
        self._loaded = True

    def _save_to_db(self, sh: SourceHealth):
        """保存单个源的健康状态到数据库"""
        try:
            with get_db() as conn:
                c = conn.cursor()
                c.execute(
                    """INSERT OR REPLACE INTO source_health
                       (source_name, total_requests, success_count, failure_count,
                        consecutive_failures, avg_latency, last_success_ts,
                        last_failure_ts, last_error, is_circuit_open, circuit_open_ts)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sh.source_name, sh.total_requests, sh.success_count,
                        sh.failure_count, sh.consecutive_failures, sh.avg_latency,
                        sh.last_success_ts, sh.last_failure_ts, sh.last_error,
                        1 if sh.is_circuit_open else 0, sh.circuit_open_ts,
                    ),
                )
                conn.commit()
        except Exception:
            pass

    def _get_or_create(self, source_name: str) -> SourceHealth:
        if source_name not in self._health:
            self._health[source_name] = SourceHealth(source_name=source_name)
        return self._health[source_name]

    def record_success(self, source_name: str, latency: float):
        """记录一次成功请求"""
        if not self._loaded:
            self.load_from_db()
        sh = self._get_or_create(source_name)
        sh.total_requests += 1
        sh.success_count += 1
        sh.consecutive_failures = 0
        sh.last_success_ts = int(time.time())
        if sh.avg_latency == 0:
            sh.avg_latency = latency
        else:
            sh.avg_latency = sh.avg_latency * 0.9 + latency * 0.1
        if sh.is_circuit_open:
            sh.is_circuit_open = False
            sh.circuit_open_ts = 0
        self._save_to_db(sh)

    def record_failure(self, source_name: str, error: str = ""):
        """记录一次失败请求"""
        if not self._loaded:
            self.load_from_db()
        sh = self._get_or_create(source_name)
        sh.total_requests += 1
        sh.failure_count += 1
        sh.consecutive_failures += 1
        sh.last_failure_ts = int(time.time())
        sh.last_error = error[:200] if error else ""
        if sh.consecutive_failures >= CIRCUIT_BREAKER_FAILURE_THRESHOLD and not sh.is_circuit_open:
            sh.is_circuit_open = True
            sh.circuit_open_ts = int(time.time())
        self._save_to_db(sh)

    def is_circuit_open(self, source_name: str) -> bool:
        """判断断路器是否打开（是否应该跳过该源）"""
        if not self._loaded:
            self.load_from_db()
        sh = self._get_or_create(source_name)
        if not sh.is_circuit_open:
            return False
        if int(time.time()) - sh.circuit_open_ts >= CIRCUIT_BREAKER_RECOVERY_TIME:
            sh.is_circuit_open = False
            sh.consecutive_failures = 0
            self._save_to_db(sh)
            return False
        return True

    def get_health(self, source_name: str) -> SourceHealth:
        """获取源的健康状态"""
        if not self._loaded:
            self.load_from_db()
        return self._get_or_create(source_name)

    def get_all_health(self) -> dict[str, SourceHealth]:
        """获取所有源的健康状态"""
        if not self._loaded:
            self.load_from_db()
        return dict(self._health)

    def get_circuit_remaining(self, source_name: str) -> int:
        """获取断路器剩余冷却时间（秒）"""
        if not self._loaded:
            self.load_from_db()
        sh = self._get_or_create(source_name)
        if not sh.is_circuit_open:
            return 0
        elapsed = int(time.time()) - sh.circuit_open_ts
        remaining = CIRCUIT_BREAKER_RECOVERY_TIME - elapsed
        return max(0, remaining)


_global_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """获取全局健康监控器单例"""
    global _global_health_monitor
    if _global_health_monitor is None:
        _global_health_monitor = HealthMonitor()
    return _global_health_monitor
