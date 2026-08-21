#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参数转换与结果序列化工具。

- 前端传入的参数为「展示值」；本模块负责转换成 easy-tdx 需要的 Python 值
  （枚举 int / 日期 int / 股票列表元组等）。
- 将 easy-tdx 返回结果（DataFrame / bytes / 标量 / 列表）序列化为前端友好结构。
"""

from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 参数值转换
# ---------------------------------------------------------------------------
def _parse_stock_line(line: str):
    """解析一行 '市场 代码' → (market_int, code)。市场缺省视为 SH。"""
    line = line.strip()
    if not line:
        return None
    # 支持空格 / 冒号 / 逗号 / tab 分隔
    for sep in (":", ",", "\t"):
        line = line.replace(sep, " ")
    parts = line.split()
    market_map = {"SH": 1, "SZ": 0, "BJ": 2}
    if parts[0].upper() in market_map:
        market = market_map[parts[0].upper()]
        code = parts[1] if len(parts) > 1 else parts[0]
    else:
        market = 1  # 默认上海
        code = parts[0]
    return (market, code.strip())


def parse_param_value(param: dict, raw_value: Any) -> Any:
    """将单个前端参数值转换为调用 easy-tdx 所需的 Python 值。"""
    ptype = param.get("type")
    # 空值处理
    if raw_value is None or raw_value == "":
        if ptype in ("number", "dateint"):
            return None
        if ptype == "bool":
            return False
        if ptype == "stocklist":
            return []
        return None

    if ptype == "enum":
        # 在 options 中按 value 找到对应 py 值
        for opt in (param.get("options") or []):
            if opt["value"] == raw_value:
                return opt["py"]
        # 找不到时原样返回（可能是直接传 py）
        return raw_value

    if ptype == "number":
        try:
            f = float(raw_value)
            return int(f) if f.is_integer() else f
        except (TypeError, ValueError):
            return None

    if ptype == "bool":
        return bool(raw_value)

    if ptype == "dateint":
        s = str(raw_value).strip()
        # 允许 Date 对象序列化后的 YYYY-MM-DD
        s = s.replace("-", "")
        return int(s) if s.isdigit() else None

    if ptype == "stocklist":
        if isinstance(raw_value, list):
            lines = raw_value
        else:
            lines = str(raw_value).splitlines()
        return [t for t in (_parse_stock_line(x) for x in lines) if t]

    if ptype == "text":
        return str(raw_value)

    # strategy / 其他透传
    return raw_value


def build_kwargs(func_def: dict, params: dict) -> dict:
    """根据功能定义与前端传入的参数，构造方法调用 kwargs。"""
    kwargs: dict[str, Any] = {}
    for param in func_def.get("params", []):
        key = param["key"]
        if key not in params:
            # 未传且非必填的参数跳过；必填但缺失由校验层处理
            continue
        kwargs[key] = parse_param_value(param, params[key])
    return kwargs


def validate_params(func_def: dict, params: dict) -> list[str]:
    """参数校验，返回错误信息列表（为空表示通过）。"""
    errors: list[str] = []
    for param in func_def.get("params", []):
        key = param["key"]
        required = param.get("required", False)
        if not required:
            continue
        val = params.get(key, None)
        if val is None or val == "":
            errors.append(f"缺少必填参数：{param['label']}")
            continue
        if param["type"] == "number" and not isinstance(val, (int, float)):
            errors.append(f"{param['label']} 必须为数字")
        if param["type"] == "stocklist":
            parsed = parse_param_value(param, val)
            if not parsed:
                errors.append(f"{param['label']} 至少包含一只股票")
        if param["type"] == "dateint":
            parsed = parse_param_value(param, val)
            if parsed is None:
                errors.append(f"{param['label']} 格式应为 YYYYMMDD")
    return errors


# ---------------------------------------------------------------------------
# 结果序列化
# ---------------------------------------------------------------------------
def _jsonify_scalar(v: Any) -> Any:
    if isinstance(v, (pd.Timestamp, _dt.datetime, _dt.date)):
        return str(v)
    if isinstance(v, float):
        if v == v and abs(v) < 1e15:  # 非 NaN
            return round(v, 6)
        return None
    if isinstance(v, (int, str, bool)) or v is None:
        return v
    return str(v)


def df_to_table(df: pd.DataFrame, max_rows: int = 5000) -> dict:
    """DataFrame → 表格结构。"""
    cols = [str(c) for c in df.columns]
    rows = []
    for _, row in df.head(max_rows).iterrows():
        rows.append([_jsonify_scalar(v) for v in row.tolist()])
    return {
        "type": "table",
        "columns": cols,
        "rows": rows,
        "row_count": int(len(df)),
        "truncated": int(len(df)) > max_rows,
    }


def list_to_table(data: Any) -> dict:
    """list[dict] / list[tuple] → 表格结构。"""
    if data and isinstance(data[0], dict):
        cols = list(data[0].keys())
        rows = [[_jsonify_scalar(d.get(c)) for c in cols] for d in data]
        return {"type": "table", "columns": cols, "rows": rows, "row_count": len(data), "truncated": False}
    if data and isinstance(data[0], (tuple, list)):
        n = len(data[0])
        cols = [f"col{i + 1}" for i in range(n)]
        rows = [[_jsonify_scalar(v) for v in row] for row in data]
        return {"type": "table", "columns": cols, "rows": rows, "row_count": len(data), "truncated": False}
    return {"type": "message", "text": str(data)}


def serialize_result(result: Any) -> dict:
    """统一序列化 easy-tdx 返回结果。"""
    if isinstance(result, pd.DataFrame):
        if result.empty:
            return {"type": "message", "text": "查询成功，但返回空数据。"}
        return df_to_table(result)
    if isinstance(result, bytes):
        # 文件类结果由 service 单独处理（落盘 + 下载链接）
        return {"type": "bytes", "raw": result}
    if isinstance(result, (list, tuple)):
        return list_to_table(result)
    if isinstance(result, dict):
        return {"type": "json", "data": result}
    return {"type": "message", "text": str(result)}
