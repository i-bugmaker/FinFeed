"""同花顺 F10 个股资料模块（f10-Web 整合）。

把独立 Web 项目 f10-Web 移植为 FinFeed 的一个独立模块：

- 数据层：``f10data`` 提供模块抓取（带 TTL 缓存）、股票搜索与元信息，
  底层复用同花顺 F10 抓取引擎（engine / modules / renderers / http_client）。
- 路由：``server.create_router("/api/f10")`` 挂载 FastAPI 路由；
  前端为独立手写 Web 页面，由主应用静态托管在 ``/f10``。
- 独立运行：``python -m finfeed.f10`` 可在 127.0.0.1 单独起服。

对外主要接口（re-export）：
    suggest(keyword)          股票搜索建议
    fetch_module(idx, code, mid)  抓取一个 F10 模块并返回结构化 JSON
    meta()                    模块清单 / 版本 / 缓存 TTL
"""

from __future__ import annotations

import os as _os

from .engine import MODULES  # noqa: F401  (re-export 供上层使用)
from .f10data import (  # noqa: F401
    ModuleFetchError,
    fetch_module,
    meta,
    suggest,
)

# 前端静态资源目录（index.html + assets/），用于主应用静态托管与独立起服。
WEB_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "web")

__all__ = [
    "WEB_DIR",
    "MODULES",
    "ModuleFetchError",
    "fetch_module",
    "meta",
    "suggest",
]
