#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：守护涨停归因报告『连板』列使用 limit_streak（对应 Bug 2 修复）。

关键不变量：report._format_limit_row 必须在『连板』列输出 limit_pool.limit_streak
（连板数），而非 open_times（开板次数）。表头与取值一旦错位，日报即给出错误结论。
"""
from collections import Counter

from finfeed.market import report as rep


def _row_cells(row: str):
    # 去掉首尾竖线后按 | 拆分并去空白
    return [c.strip() for c in row.strip().strip("|").split("|")]


def test_format_limit_row_uses_limit_streak_not_open_times():
    r = {
        "code": "600000",
        "name": "浦发银行",
        "reason": "银行",
        "open_times": 5,       # 开板次数：绝不应出现在『连板』列
        "limit_streak": 3,     # 连板数：『连板』列应取此值
        "limit_amount": 1.2,
        "circ_mv": 3000.0,
    }
    row = rep._format_limit_row(1, r, "浦发银行", None, None, "-")
    cells = _row_cells(row)
    # 表头: #|代码|名称|行业|连板|封单(亿)|流通市值(亿)|龙虎榜净买(万)|主力净流入(万)|相关新闻
    assert cells[4] == "3", f"连板列应为 limit_streak=3，实际={cells[4]}"
    assert cells[4] != "5", "连板列不应误用 open_times"


def test_format_limit_row_billboard_and_moneyflow_formatting():
    r = {
        "code": "000001",
        "name": "平安银行",
        "reason": "银行",
        "limit_streak": 2,
        "limit_amount": 0.5,
        "circ_mv": 2000.0,
    }
    b = {"net_amount": 1234567}   # 龙虎榜净买 123.4567 万
    mf = 9876543.0                # 主力净流入 987.6543 万
    row = rep._format_limit_row(2, r, "平安银行", b, mf, "-")
    cells = _row_cells(row)
    assert cells[4] == "2"        # 连板
    assert cells[7] == "123"      # 龙虎榜净买(万)：1234567/1e4 ≈ 123
    assert cells[8] == "988"      # 主力净流入(万)：9876543/1e4 ≈ 988（四舍五入）


def test_defaultdict_count_returns_counter():
    c = rep.defaultdict_count(["银行", "银行", "地产"])
    assert isinstance(c, Counter)
    assert c["银行"] == 2
    assert c["地产"] == 1
