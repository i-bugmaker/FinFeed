#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""股票监控模块（FinFeed Watchlist Monitor）。

功能组成
--------
1. 股票导入管理：手动单个 / 文本批量 / 图片截图（OCR）三种导入方式，
   导入时校验代码有效性（正则 + 板块规则 + 行情库在线核验），
   支持列表查看 / 备注编辑 / 删除。
2. 舆情聚合展示：每只监控股票独立聚合「系统内消息」（news 表按代码/
   名称匹配）与「系统外消息」（东方财富个股资讯 + 公告接口，后台线程
   周期抓取入库），按股票分组返回；SSE 实时推送 + since_ts 离线补全。
3. AI 智能分析：复用 finfeed.llm（OpenAI 兼容多供应商）对单只股票的
   聚合舆情做消息解读 / 情绪倾向 / 影响评估，结果持久化并与股票关联。

对外入口：``finfeed.stock_monitor.router.router``（FastAPI 路由，
前缀 ``/api/stock-monitor``）。
"""

from finfeed.stock_monitor.router import router

__all__ = ["router"]
