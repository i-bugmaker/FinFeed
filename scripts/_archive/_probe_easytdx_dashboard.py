# -*- coding: utf-8 -*-
"""临时探针2：验证仪表盘后端各榜单逻辑（排序字段/返回列）。"""
import json
import time

from easy_tdx import MacClient, TdxClient
from easy_tdx.mac.enums import Category, SortOrder, SortType


def show(name, df, extra=None):
    cols = list(df.columns) if df is not None else None
    head = []
    if df is not None:
        for _, row in df.head(5).iterrows():
            head.append({str(c): (None if v is None else str(v)) for c, v in row.items()})
    print("=====", name, "| rows:", 0 if df is None else len(df), "| cols:", cols, extra or "")
    print(json.dumps(head, ensure_ascii=False, indent=1))


with MacClient() as mc:
    t0 = time.time()
    show("HY by main_net_amount", mc.get_board_ranking(board_type=0, top_n=20, sort_by="main_net_amount", ascending=False), f"({time.time()-t0:.1f}s)")
    t0 = time.time()
    show("stock up(top by CHANGE_PCT desc)", mc.get_stock_quotes_list(category=Category.A, count=20, sort_type=SortType.CHANGE_PCT, sort_order=SortOrder.DESC), f"({time.time()-t0:.1f}s)")
    t0 = time.time()
    show("stock down(top by CHANGE_PCT asc)", mc.get_stock_quotes_list(category=Category.A, count=20, sort_type=SortType.CHANGE_PCT, sort_order=SortOrder.ASC), f"({time.time()-t0:.1f}s)")
    t0 = time.time()
    show("stock amount(top)", mc.get_stock_quotes_list(category=Category.A, count=20, sort_type=SortType.TOTAL_AMOUNT, sort_order=SortOrder.DESC), f"({time.time()-t0:.1f}s)")
    t0 = time.time()
    show("unusual market=2", mc.get_unusual(market=2, start=0, count=20), f"({time.time()-t0:.1f}s)")

with TdxClient() as tc:
    show("market_stat", tc.get_market_stat())
