#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A 股板块分类（基于代码前缀 + 市场字段）。

板块划分（与交易所规则一致）：
    主板    沪市 600/601/603/605，深市 000/001/002/003
    科创板  688/689
    创业板  300/301
    北交所  8xxxxx / 4xxxxx / 920xxx（market==2 亦归入北交所）
"""

from __future__ import annotations

# 板块代码 -> 中文标签
BOARD_LABELS: dict[str, str] = {
    "main": "主板",
    "kcb": "科创板",
    "cyb": "创业板",
    "bj": "北交所",
}

# 板块代码 -> 简短标签（前端徽标用）
BOARD_SHORT: dict[str, str] = {
    "main": "主",
    "kcb": "科",
    "cyb": "创",
    "bj": "京",
}

_MAIN_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
_KCB_PREFIXES = ("688", "689")
_CYB_PREFIXES = ("300", "301")
_BJ_PREFIXES = ("8", "4", "920")


def classify_board(code: str | int | None, market: int | None = None) -> str:
    """将股票归类为 main / kcb / cyb / bj。

    优先按代码前缀判定；代码缺失或无法判定时退回 market 字段
    （通达信市场约定：0=深交所, 1=上交所, 2=北交所）。
    """
    code = str(code or "").zfill(6)
    if market == 2:
        return "bj"
    if code.startswith(_KCB_PREFIXES):
        return "kcb"
    if code.startswith(_CYB_PREFIXES):
        return "cyb"
    if code.startswith(_MAIN_PREFIXES):
        return "main"
    if code.startswith(_BJ_PREFIXES):
        return "bj"
    # 无前缀信息：按市场兜底
    if market == 0 or market == 1:
        return "main"
    return "main"


def board_label(board: str) -> str:
    return BOARD_LABELS.get(board, board or "未知")
