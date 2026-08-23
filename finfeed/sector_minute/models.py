# -*- coding: utf-8 -*-
"""板块分时 —— 数据模型。

与 easy-tdx / pandas 解耦的纯数据容器，直接序列化为 JSON 供前端消费。
涨跌幅单位统一为「%」，金额单位为「元」。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class BoardMeta:
    """板块列表条目（含实时涨跌幅）。"""

    market: int = 0
    code: str = ""
    name: str = ""
    board_type: str = ""        # hy/hy2/gn/fg/dq
    price: float = 0.0          # 板块指数现价
    pre_close: float = 0.0      # 昨收
    rise_pct: float = 0.0       # 涨跌幅 %


@dataclass
class StockMeta:
    """个股池条目（沪深 A 股全量，含实时涨跌幅）。"""

    market: int = 0
    code: str = ""
    name: str = ""
    price: float = 0.0
    change_pct: float = 0.0


@dataclass
class TickPoint:
    """分时数据点。"""

    time: str = ""              # "09:30:00"
    price: float = 0.0
    avg: float = 0.0            # 分时均价
    vol: int = 0                # 该分钟成交量（手）


@dataclass
class TickChart:
    """单标的单日分时图（板块 / 个股通用）。"""

    kind: str = "board"         # board | stock
    market: int = 0
    code: str = ""
    name: str = ""
    board_type: str = ""        # 板块类型（个股为空）
    pre_close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    change_pct: float = 0.0     # 涨跌幅 %
    change_amt: float = 0.0     # 涨跌额
    points: list[TickPoint] = field(default_factory=list)
    ts: str = ""                # 最后更新时间 HH:MM:SS


@dataclass
class Subscription:
    """前端订阅的对比标的。"""

    kind: str = "board"         # board | stock
    market: int = 0
    code: str = ""
    name: str = ""
    board_type: str = ""

    @property
    def key(self) -> str:
        # 板块须带 board_type，否则 hy/hy2/gn 等同 code 板块会被误判为同一标的
        if self.kind == "board":
            return f"board:{self.board_type}:{self.market}:{self.code}"
        return f"{self.kind}:{self.market}:{self.code}"


def to_dict(obj: Any) -> dict[str, Any]:
    """dataclass → dict（递归）。"""
    return asdict(obj)
