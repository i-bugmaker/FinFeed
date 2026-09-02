#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinFeed FastAPI 后端包。

Web 单轨：本模块在 8866 提供服务，旧的 stdlib ``server.py`` 已退役。
业务函数（db_* / 健康监控 / 导出 / llm·calendar·market 适配层）
与 SSE 增量广播通道（shared._sse_clients / broadcast_new_news）全部收敛在
``finfeed.ui.web_fastapi.shared`` 共享运行时，确保 finance/forum 双水位线、
幂等、慢客户端降级等既有语义 100% 保留。
"""
