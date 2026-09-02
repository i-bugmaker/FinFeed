#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""easy-tdx 任务执行服务。

职责：
- 管理内存任务表（状态 / 日志 / 进度 / 结果）。
- 在线程中执行 easy-tdx 调用，捕获其 logging 输出作为实时进度日志，
  并基于日志中的 "n/total" 估算进度百分比。
- 处理文件落盘与下载链接、参数校验、异常处理。
- 仅通过 easy-tdx 公开 API（TdxClient / MacClient / ExTdxClient / CnInfoClient /
  回测注册表 / ChanlunAnalyser）调用，不依赖其内部实现。
"""

from __future__ import annotations

import logging
import re
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from . import converters as cv
from .registry import get_function

logger = logging.getLogger("easytdx_service")

# 任务结果落盘目录（文件类结果）
_OUTPUT_DIR = Path(__file__).resolve().parent / "output"
_OUTPUT_DIR.mkdir(exist_ok=True)

# 任务内存表
_TASKS: dict[str, dict] = {}
_TASKS_LOCK = threading.Lock()

_PROGRESS_RE = re.compile(r"(\d+)\s*/\s*(\d+)")

_CLIENT_CLASSES = {}


def _client_class(name: str):
    if not _CLIENT_CLASSES:
        from easy_tdx import ExTdxClient, MacClient, TdxClient
        from easy_tdx.cninfo import CninfoClient
        _CLIENT_CLASSES.update(
            tdx=TdxClient, mac=MacClient, ex=ExTdxClient, cninfo=CninfoClient
        )
    return _CLIENT_CLASSES[name]


class _LogCapture(logging.Handler):
    """将 easy-tdx 的日志实时写入任务日志列表，并估算进度。"""

    def __init__(self, task: dict):
        super().__init__()
        self.task = task

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        with _TASKS_LOCK:
            self.task["logs"].append({"t": time.time(), "level": record.levelname, "msg": msg})
            # 进度估算
            m = _PROGRESS_RE.search(msg)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                if total > 0:
                    self.task["progress"] = max(self.task["progress"], round(done / total * 100))
        # 控制内存：仅保留最近 500 条日志
        if len(self.task["logs"]) > 500:
            with _TASKS_LOCK:
                self.task["logs"] = self.task["logs"][-500:]


def create_task(func_id: str, params: dict) -> dict:
    """创建并启动一个执行任务。"""
    func_def = get_function(func_id)
    if not func_def:
        raise ValueError(f"未知功能: {func_id}")

    task_id = uuid.uuid4().hex[:12]
    task = {
        "task_id": task_id,
        "func_id": func_id,
        "func_label": func_def["label"],
        "params": params,
        "status": "running",  # running | success | error
        "progress": 0,
        "logs": [],
        "result": None,
        "error": None,
        "started_at": time.time(),
        "finished_at": None,
        "file_path": None,
    }
    with _TASKS_LOCK:
        _TASKS[task_id] = task

    t = threading.Thread(target=_run, args=(task, func_def), daemon=True)
    t.start()
    return {
        "task_id": task_id,
        "func_id": func_id,
        "label": func_def["label"],
        "status": "running",
    }


def get_task(task_id: str) -> dict | None:
    with _TASKS_LOCK:
        return dict(_TASKS.get(task_id, {})) if task_id in _TASKS else None


def list_tasks(limit: int = 20) -> list[dict]:
    with _TASKS_LOCK:
        items = list(_TASKS.values())
    items.sort(key=lambda x: x["started_at"], reverse=True)
    out = []
    for it in items[:limit]:
        out.append({
            "task_id": it["task_id"], "func_id": it["func_id"],
            "func_label": it["func_label"], "status": it["status"],
            "progress": it["progress"], "started_at": it["started_at"],
            "error": it["error"],
        })
    return out


def _run(task: dict, func_def: dict) -> None:
    handler = _LogCapture(task)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        # 参数校验
        errors = cv.validate_params(func_def, task["params"])
        if errors:
            raise ValueError("；".join(errors))

        result = _dispatch(func_def, task["params"])

        # 序列化
        if isinstance(result, bytes):
            # 文件落盘
            fname = _safe_filename(task, func_def)
            fpath = _OUTPUT_DIR / fname
            fpath.write_bytes(result)
            with _TASKS_LOCK:
                task["file_path"] = str(fpath)
            task["result"] = {
                "type": "file",
                "filename": fname,
                "size": len(result),
                "download_url": f"/api/easytdx/download/{task['task_id']}",
            }
        elif isinstance(result, dict) and result.get("type") == "bytes":
            # serialize_result 把 bytes 标记为 type=bytes
            raw = result["raw"]
            fname = _safe_filename(task, func_def)
            fpath = _OUTPUT_DIR / fname
            fpath.write_bytes(raw)
            with _TASKS_LOCK:
                task["file_path"] = str(fpath)
            task["result"] = {
                "type": "file",
                "filename": fname,
                "size": len(raw),
                "download_url": f"/api/easytdx/download/{task['task_id']}",
            }
        elif isinstance(result, dict) and result.get("type") == "file_path":
            fpath = Path(result["path"])
            if fpath.exists():
                with _TASKS_LOCK:
                    task["file_path"] = str(fpath)
                task["result"] = {
                    "type": "file",
                    "filename": fpath.name,
                    "size": fpath.stat().st_size,
                    "download_url": f"/api/easytdx/download/{task['task_id']}",
                }
            else:
                task["result"] = {"type": "message", "text": "下载完成但文件未找到。"}
        else:
            task["result"] = _json_safe(cv.serialize_result(result))
        with _TASKS_LOCK:
            task["status"] = "success"
            task["progress"] = 100
    except Exception as e:  # noqa: BLE001
        logger.exception("easytdx task %s failed", task["task_id"])
        with _TASKS_LOCK:
            task["status"] = "error"
            task["error"] = str(e)
            task["logs"].append({
                "t": time.time(), "level": "ERROR",
                "msg": f"{e.__class__.__name__}: {e}",
            })
            task["logs"].append({
                "t": time.time(), "level": "ERROR",
                "msg": traceback.format_exc(limit=3),
            })
    finally:
        root.removeHandler(handler)
        with _TASKS_LOCK:
            task["finished_at"] = time.time()


def _safe_filename(task: dict, func_def: dict) -> str:
    base = func_def.get("id", "file")
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(task["started_at"]))
    ext = ".bin"
    # 依据功能推断扩展名
    fid = func_def["id"]
    if "pdf" in fid:
        ext = ".pdf"
    elif "report" in fid or "file" in fid:
        ext = ".dat"
    elif "financial" in fid:
        ext = ".zip"
    return f"{base}_{ts}{ext}"


# 派发执行
def _dispatch(func_def: dict, params: dict):
    client = func_def["client"]
    if client in ("tdx", "mac", "ex"):
        return _call_client_method(client, func_def, params)
    if client == "cninfo":
        return _call_cninfo(func_def, params)
    if client == "ping":
        return _call_ping(params)
    if client == "host":
        return _call_host(func_def, params)
    if client == "chanlun":
        return _call_chanlun(func_def, params)
    if client == "backtest":
        return _call_backtest(func_def, params)
    raise ValueError(f"未知执行器: {client}")


def _call_client_method(client: str, func_def: dict, params: dict):
    cls = _client_class(client)
    kwargs = cv.build_kwargs(func_def, params)
    with cls() as c:
        method = getattr(c, func_def["method"])
        return method(**kwargs)


def _call_cninfo(func_def: dict, params: dict):
    """CninfoClient 不支持上下文管理器，单独处理。"""
    from easy_tdx.cninfo import CninfoClient

    method = func_def["method"]
    client = CninfoClient(timeout=15)
    if method == "get_announcements":
        code = params.get("code")
        count = int(params.get("count", 30) or 30)
        page = int(params.get("page", 1) or 1)
        return client.get_announcements(code, count=count, page=page)
    if method == "download_pdf":
        code = params.get("code")
        index = int(params.get("index", 0) or 0)
        df = client.get_announcements(code, count=max(index + 1, 30))
        if df is None or df.empty or index >= len(df):
            total = 0 if df is None else len(df)
            return f"公告序号 {index} 超出范围（共 {total} 条）。请先查询公告列表。"
        row = df.iloc[index]
        path = client.download_pdf(row, dest_dir=str(_OUTPUT_DIR))
        return {"type": "file_path", "path": path}
    raise ValueError(f"未支持的 cninfo 方法: {method}")


def _call_ping(params: dict):
    from easy_tdx import ping_all, ping_mac_all
    scope = params.get("scope", "tdx")
    rows = []
    if scope in ("tdx", "all"):
        for host, latency in ping_all():
            rows.append({"scope": "tdx", "host": host,
                         "latency_ms": round(latency * 1000, 1) if latency else None})
    if scope in ("mac", "all"):
        for host, latency in ping_mac_all():
            rows.append({"scope": "mac", "host": host,
                         "latency_ms": round(latency * 1000, 1) if latency else None})
    return rows


def _call_host(func_def: dict, params: dict):
    from easy_tdx import ping_all, ping_mac_all
    from easy_tdx.config import (
        get_best_ex_host,
        get_best_host,
        get_best_mac_host,
        get_calc_hosts,
        get_ex_hosts,
        get_known_hosts,
        get_mac_hosts,
        save_best_host,
        save_best_mac_host,
    )
    method = func_def["method"]
    which = params.get("which", "tdx")
    if method == "info":
        return {
            "best_tdx_host": get_best_host(),
            "known_tdx_hosts": list(get_known_hosts()),
            "calc_hosts": list(get_calc_hosts()),
            "best_mac_host": get_best_mac_host(),
            "mac_hosts": list(get_mac_hosts()),
            "best_ex_host": get_best_ex_host(),
            "ex_hosts": list(get_ex_hosts()),
        }
    if method == "refresh":
        saved = {}
        if which in ("tdx", "all"):
            hosts = ping_all()
            if hosts:
                save_best_host(hosts[0][0])
                saved["tdx"] = hosts[0][0]
        if which in ("mac", "all"):
            hosts = ping_mac_all()
            if hosts:
                save_best_mac_host(hosts[0][0])
                saved["mac"] = hosts[0][0]
        return {
            "refreshed": which,
            "saved": saved,
            "best_tdx_host": get_best_host(),
            "best_mac_host": get_best_mac_host(),
            "best_ex_host": get_best_ex_host(),
        }
    return {"ok": True}


def _call_chanlun(func_def: dict, params: dict):
    from easy_tdx import Adjust, MacClient, Period
    from easy_tdx.chanlun import ChanlunAnalyser

    # 枚举类参数（market/period/adjust）经注册表 schema 转换后才是整数值
    kwargs = cv.build_kwargs(func_def, params)
    market = kwargs.get("market", 1)
    code = kwargs["code"]
    period = kwargs.get("period", 4)
    count = int(kwargs.get("count", 300))
    adjust = kwargs.get("adjust", 1)

    with MacClient() as c:
        df = c.get_stock_kline(
            market, code, Period(period), count=count, adjust=Adjust(adjust)
        )
    if df is None or df.empty:
        return "未获取到 K 线数据（该标的或网络可能不可用）。"

    # 缠论分析器需要 date/open/high/low/close/volume 列
    df = df.rename(columns={"datetime": "date", "vol": "volume"})
    if "date" not in df.columns and "datetime" in df.columns:
        df = df.rename(columns={"datetime": "date"})
    if "volume" not in df.columns and "vol" in df.columns:
        df = df.rename(columns={"vol": "volume"})

    freq_map = {0: "5MIN", 1: "15MIN", 2: "30MIN", 3: "60MIN", 4: "DAILY",
                5: "WEEKLY", 6: "MONTHLY", 7: "1MIN", 8: "MINS", 9: "DAYS"}
    freq = freq_map.get(int(period), "DAILY")
    analyser = ChanlunAnalyser(code, freq)
    result = analyser.process_klines(df)
    d = result.to_dict()
    # 把关键列表结构转成表格展示
    return _chanlun_to_table(d, code)


def _chanlun_to_table(d: dict, code: str) -> dict:
    """将缠论结果转为前端可展示结构（合并笔/段/中枢/买卖点表）。

    返回普通 dict —— serialize_result 会对 dict 统一包成 {"type":"json",...}。
    """
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, list):
            # 笔/段/中枢/买卖点 → 表格
            rows = []
            for item in v:
                if hasattr(item, "__dict__"):
                    rows.append(item.__dict__)
                elif isinstance(item, dict):
                    rows.append(item)
                else:
                    rows.append({"value": str(item)})
            out[k] = {"count": len(rows), "samples": rows[:50]}
        elif isinstance(v, dict):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _call_backtest(func_def: dict, params: dict):
    from easy_tdx import Adjust, MacClient, Period
    from easy_tdx.backtest import BacktestEngine
    from easy_tdx.backtest.strategies import get_registry

    # 枚举类参数（market/period/adjust）经注册表 schema 转换后才是整数值
    kwargs = cv.build_kwargs(func_def, params)
    market = kwargs.get("market", 1)
    code = kwargs["code"]
    period = kwargs.get("period", 4)
    count = int(kwargs.get("count", 500))
    adjust = kwargs.get("adjust", 1)
    strategy_name = kwargs.get("strategy", "")
    cash = float(kwargs.get("cash", 100000))

    # 取 K 线
    with MacClient() as c:
        df = c.get_stock_kline(
            market, code, Period(period), count=count, adjust=Adjust(adjust)
        )
    if df is None or df.empty:
        return "未获取到 K 线数据，无法回测。"

    df = df.rename(columns={"datetime": "date", "vol": "volume"})

    reg = get_registry()
    rs = reg.get(strategy_name)
    if rs is None:
        return f"未找到策略: {strategy_name}"
    # 用注册表声明的参数实例化（未提供的取默认）
    strat_params = {}
    for pp in (rs.params or []):
        if pp.name in params and params[pp.name] not in (None, ""):
            v = params[pp.name]
            # 按声明类型转换（前端可能传来字符串）
            if pp.type is int:
                try:
                    v = int(float(v))
                except (TypeError, ValueError):
                    v = pp.default
            elif pp.type is float:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    v = pp.default
            strat_params[pp.name] = v
    # RegisteredStrategy.build(params: dict | None) —— 传参数字典，空则用默认
    strategy_instance = rs.build(strat_params or None)

    engine = BacktestEngine(strategy=strategy_instance, cash=cash)
    result = engine.run(df)

    perf = getattr(result, "performance", None)
    trades = getattr(result, "trades", None)
    equity = getattr(result, "equity_curve", None)

    data: dict[str, Any] = {"performance": _to_dict(perf)}
    if trades is not None:
        data["trades"] = [_to_dict(t) for t in trades][:200]
    # 资金曲线 DataFrame → 记录列表（前端可直接画线）
    if equity is not None:
        try:
            data["equity"] = equity.to_dict("records")[:500]
        except Exception:  # noqa: BLE001
            try:
                data["equity"] = equity.to_dict()
            except Exception:  # noqa: BLE001
                data["equity"] = None
    return data


def _to_dict(obj):
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            return str(obj)
    if hasattr(obj, "__dict__"):
        return {k: _jsonable(v) for k, v in vars(obj).items()}
    return _jsonable(obj)


def _jsonable(v):
    import datetime as _dt
    if isinstance(v, (pd.Timestamp, _dt.datetime, _dt.date)):
        return str(v)
    if isinstance(v, float):
        return round(v, 6) if v == v else None
    try:
        import numpy as np
        if isinstance(v, np.generic):
            item = v.item()
            if isinstance(item, (_dt.datetime, _dt.date)):
                return str(item)
            return _jsonable(item)
    except Exception:  # noqa: BLE001
        pass
    return v


def _json_safe(v):
    """递归把结果转换为 JSON 可序列化结构（numpy/时间/元组/DataFrame 兜底）。"""
    import datetime as _dt
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, pd.DataFrame):
        return _json_safe(v.to_dict("records"))
    if isinstance(v, pd.Series):
        return _json_safe(v.to_dict())
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, (pd.Timestamp, _dt.datetime, _dt.date)):
        return str(v)
    if isinstance(v, float):
        return round(v, 6) if v == v else None
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return _json_safe(v.item())
    except Exception:  # noqa: BLE001
        pass
    return v
