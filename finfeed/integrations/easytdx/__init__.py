#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinFeed × easy-tdx 集成：通过 easy-tdx 公开 API 访问通达信行情数据。

仅调用 easy_tdx 的对外接口（TdxClient / MacClient / ExTdxClient / CnInfoClient /
回测注册表 / ChanlunAnalyser），不复制其源码实现。
"""

from .router import router

__all__ = ["router"]
