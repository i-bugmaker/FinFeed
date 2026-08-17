#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：同花顺「涨停聚焦」四模块规整不变量。

聚焦纯函数（字段映射 / 合并 / 衍生指标），不触碰网络与数据库：
- dataapi 数字字段 ID（199112/10/9001/330323/330324）必须正确映射到命名结构
- mobileapi 命名字段（stock_code/stock_name/...）必须正确映射
- 涨停池合并：基础行必须按代码用富化源补全连板数 / 封板时间 / 主力净额
- 涨停强度衍生指标：炸板率 = 炸板/(涨停+炸板)，封板率 = 涨停/(涨停+炸板)
- 风向标股 tab_list 结构映射
"""

from finfeed.market import ths_limitup as lu


def test_norm_dataapi_pool_item_maps_field_ids():
    raw = {"199112": "600000", "10": "浦发银行", "9001": "银行",
           "330323": 12.34, "330324": 9.98}
    out = lu._norm_dataapi_pool_item(raw)
    assert out["code"] == "600000"
    assert out["name"] == "浦发银行"
    assert out["reason"] == "银行"
    assert out["price"] == 12.34
    assert out["change_pct"] == 9.98


def test_norm_mobile_stock_maps_named_fields():
    raw = {
        "stock_code": "300120", "stock_name": "润泽科技", "market_code": "0",
        "list_board": "chinext", "price": 9.26, "change": 19.9482,
        "amplitude": 12.3, "limit_up_reason": "专用设备",
        "continue_day": 3, "limit_up_time": "09:35:10",
        "main_net_amount": 1.23e8, "effective_circulation": 50.0,
        "effective_turnover_ratio": 6.7, "is_st": 0, "is_new": 0,
    }
    out = lu._norm_mobile_stock(raw)
    assert out["code"] == "300120"
    assert out["name"] == "润泽科技"
    assert out["board"] == "chinext"
    assert out["price"] == 9.26
    assert out["change_pct"] == 19.9482
    assert out["continue_day_cnt"] == 3
    assert out["limit_up_time"] == "09:35:10"
    assert out["main_net_amount"] == 1.23e8
    assert out["reason"] == "专用设备"


def test_merge_up_pool_enriches_basic_with_rich():
    basic = [{"199112": "600000", "10": "浦发银行", "330323": 10.0, "330324": 10.0}]
    rich = [{
        "code": "600000", "name": "浦发银行", "board": "main",
        "continue_day_cnt": 2, "limit_up_time": "10:00:00",
        "main_net_amount": 5.0e7, "reason": "银行", "price": 10.0,
        "change_pct": 10.0, "amplitude": 8.0, "effective_circulation": 3000.0,
        "turnover_ratio": 1.2,
    }]
    merged = lu._merge_up_pool(basic, rich)
    assert len(merged) == 1
    m = merged[0]
    # 基础行缺连板数/封板时间，必须由富化源补全
    assert m["continue_day_cnt"] == 2
    assert m["limit_up_time"] == "10:00:00"
    assert m["main_net_amount"] == 5.0e7
    assert m["board"] == "main"
    assert m["code"] == "600000"


def test_merge_up_pool_basic_only_when_rich_missing():
    basic = [{"199112": "600111", "10": "包钢股份", "330323": 2.0, "330324": 10.0}]
    merged = lu._merge_up_pool(basic, [])
    assert merged[0]["code"] == "600111"
    assert merged[0]["continue_day_cnt"] == 0  # 无富化源时缺省为 0


def test_intensity_metrics_broken_and_seal_rate():
    m = lu._intensity_metrics(80, 20, 10)
    assert m["limit_up"] == 80
    assert m["broken"] == 20
    assert m["lower"] == 10
    # 炸板率 = 20 / (80+20) = 0.2
    assert abs(m["broken_rate"] - 0.2) < 1e-9
    # 封板率 = 80 / (80+20) = 0.8
    assert abs(m["seal_rate"] - 0.8) < 1e-9


def test_intensity_metrics_zero_safe():
    m = lu._intensity_metrics(0, 0, 0)
    assert m["broken_rate"] == 0.0
    assert m["seal_rate"] == 0.0


def test_norm_wind_tabs():
    tabs = [{
        "tab_name": "高位股", "average_change": 2.31, "stock_num": 8,
        "stock_list": [{
            "stock_code": "300120", "stock_name": "润泽科技", "reason": "专用设备",
            "price": "9.26", "change": "19.9482", "fiveRise": 45.2, "tags": "AI",
        }],
    }]
    out = lu._norm_wind_tabs(tabs)
    assert out[0]["tab_name"] == "高位股"
    assert out[0]["average_change"] == 2.31
    assert out[0]["stock_num"] == 8
    s = out[0]["stocks"][0]
    assert s["stock_code"] == "300120"
    assert s["five_rise"] == 45.2
    assert s["tags"] == "AI"


def test_ymd_conversion():
    assert lu._ymd("2026-08-14") == "20260814"


def test_num_int_robustness():
    assert lu._num(None) == 0.0
    assert lu._num("") == 0.0
    assert lu._num("12.5") == 12.5
    assert lu._int(None) == 0
    assert lu._int("3.9") == 3
    assert lu._int("abc") == 0
