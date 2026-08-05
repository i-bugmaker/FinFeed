#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinFeed LLM 智能分析模块
================================

独立模块，负责：
  1. 自定义大语言模型配置管理（base_url / api_key / model，OpenAI 兼容协议）
  2. 连通性检测（网络可达 + 鉴权有效 + 模型可用）
  3. 按时间窗口（24 / 48 / 72 小时）抓取库内新闻
  4. map-reduce 分块归纳，输出结构化 Markdown 复盘报告
  5. 报告持久化与历史管理

与主链路解耦：不修改抓取/去重/存储流程，仅新增独立表与独立路由。

对外入口：
    from finfeed.llm import api as llm_api      # HTTP 路由处理
    from finfeed.llm.service import get_service  # 任务调度
"""

__all__ = [
    "schema",
    "config",
    "client",
    "collector",
    "prompts",
    "analyzer",
    "store",
    "service",
    "api",
]

MODULE_VERSION = "1.0.0"
