#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日历事件统一数据模型

四类异构数据源（财经日历 / 股市日历 / 新股日历 / 全球经济）归一化到同一结构，
未使用的字段留空，由前端按 cal_type 决定展示哪些列。
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Dict


@dataclass
class CalendarEvent:
    """统一日历事件"""

    cal_type: str                    # finance | stock | ipo | global
    event_date: str                  # YYYY-MM-DD（主日期，按日查询用）
    event_key: str                   # 源内唯一键，用于幂等 upsert
    title: str = ""                  # 事件标题
    end_date: str = ""               # YYYY-MM-DD，跨天事件的结束日
    event_time: str = ""             # HH:MM
    category: str = ""               # 一级分类（对应官网 Tab）
    sub_type: str = ""               # 原始细分类型（FE_TYPE / EVENT_TYPE / DATE_TYPE）
    content: str = ""                # 详情
    code: str = ""                   # 证券代码
    name: str = ""                   # 证券简称
    region: str = ""                 # 国家 / 地区
    importance: int = 0              # 0 未知 / 1 低 / 2 中 / 3 高
    period: str = ""                 # 报告期
    prev_value: str = ""             # 前值
    forecast_value: str = ""         # 预测值
    actual_value: str = ""           # 公布值
    url: str = ""                    # 外链
    extra: Dict[str, Any] = field(default_factory=dict)
    updated_ts: int = 0

    # ---------- 序列化 ----------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_row(self) -> tuple:
        """转为 SQL 参数元组（顺序与 store.INSERT_COLUMNS 一致）"""
        return (
            self.cal_type, self.event_key, self.event_date, self.end_date,
            self.event_time, self.category, self.sub_type, self.title,
            self.content, self.code, self.name, self.region, self.importance,
            self.period, self.prev_value, self.forecast_value, self.actual_value,
            self.url, json.dumps(self.extra, ensure_ascii=False), self.updated_ts,
        )

    @staticmethod
    def from_row(row) -> Dict[str, Any]:
        """sqlite3.Row -> dict（供 API 直接返回）"""
        d = dict(row)
        raw = d.pop("extra", "") or ""
        try:
            d["extra"] = json.loads(raw) if raw else {}
        except (ValueError, TypeError):
            d["extra"] = {}
        return d


# 是否为「跨天」事件
def is_multi_day(ev: CalendarEvent) -> bool:
    return bool(ev.end_date) and ev.end_date != ev.event_date
