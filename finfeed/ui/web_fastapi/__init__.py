#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinFeed FastAPI 后端包（方案 D 新后端）。

双轨策略：保留旧 server.py（stdlib）在 8867 作 fallback，本模块在 8866 提供服务。
本模块只替换"HTTP 壳"，业务函数（db_* / 健康监控 / 导出 / llm·calendar·market 适配层）
与 SSE 增量广播通道（shared._sse_clients / broadcast_new_news）全部复用
``finfeed.ui.web.shared`` 共享运行时，以确保 finance/forum 双水位线、幂等、
慢客户端降级等既有语义 100% 保留。
"""
