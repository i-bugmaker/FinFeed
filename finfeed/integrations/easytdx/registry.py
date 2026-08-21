#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""easy-tdx 功能注册表（数据驱动）。

本模块仅描述 easy-tdx 对外提供的公开接口（TdxClient / MacClient / ExTdxClient /
CnInfoClient / 回测注册表 / 缠论分析器 / 主机探测），**不复制任何 easy-tdx 源码**，
运行期由 service.py 通过 getattr 反射调用对应方法。

每条功能定义：
    id       唯一标识
    group    所属功能分组（见 GROUPS）
    label    中文名
    client   执行器类型：tdx / mac / ex / cninfo / ping / host / chanlun / backtest
    method   客户端方法名（client_method 类使用）
    result   结果类型：table / file / message / chart
    chart    图表提示（可选）：candle / line / fund / tick
    long     是否长耗时（开启日志流式进度）
    params   参数字段 schema（前端据此渲染表单）
"""

from __future__ import annotations

# ----------------------------------------------------------------------------
# 枚举选项（value 为前端展示，py 为传给 easy-tdx 的 Python 值）
# ----------------------------------------------------------------------------
MARKET_OPTS = [
    {"label": "上海 SH", "value": "SH", "py": 1},
    {"label": "深圳 SZ", "value": "SZ", "py": 0},
    {"label": "北京 BJ", "value": "BJ", "py": 2},
]

# TdxClient 的 KlineCategory 整数值（与 easy_tdx.models.KlineCategory 对齐）
KL_OPTS = [
    {"label": "1分钟", "value": "MIN_1", "py": 7},
    {"label": "5分钟", "value": "MIN_5", "py": 0},
    {"label": "15分钟", "value": "MIN_15", "py": 1},
    {"label": "30分钟", "value": "MIN_30", "py": 2},
    {"label": "60分钟", "value": "MIN_60", "py": 3},
    {"label": "日线", "value": "DAY", "py": 4},
    {"label": "周线", "value": "WEEK", "py": 5},
    {"label": "月线", "value": "MONTH", "py": 6},
    {"label": "年线", "value": "YEAR", "py": 9},
]

# MacClient 的 Period 整数值
PERIOD_OPTS = [
    {"label": "1分钟", "value": "MIN_1", "py": 7},
    {"label": "5分钟", "value": "MIN_5", "py": 0},
    {"label": "15分钟", "value": "MIN_15", "py": 1},
    {"label": "30分钟", "value": "MIN_30", "py": 2},
    {"label": "60分钟", "value": "MIN_60", "py": 3},
    {"label": "日线", "value": "DAILY", "py": 4},
    {"label": "周线", "value": "WEEKLY", "py": 5},
    {"label": "月线", "value": "MONTHLY", "py": 6},
    {"label": "多分钟", "value": "MINS", "py": 8},
    {"label": "多日", "value": "DAYS", "py": 9},
]

ADJUST_OPTS = [
    {"label": "不复权", "value": "NONE", "py": 0},
    {"label": "前复权", "value": "QFQ", "py": 1},
    {"label": "后复权", "value": "HFQ", "py": 2},
]

BOARD_OPTS = [
    {"label": "行业一级", "value": "HY", "py": 0},
    {"label": "行业二级", "value": "HY2", "py": 1},
    {"label": "概念", "value": "GN", "py": 3},
    {"label": "风格", "value": "FG", "py": 4},
    {"label": "地区", "value": "DQ", "py": 5},
    {"label": "其他", "value": "OTHER", "py": 6},
    {"label": "业绩一级", "value": "YJ_LEVEL1", "py": 7},
    {"label": "业绩二级", "value": "YJ_LEVEL2", "py": 8},
    {"label": "业绩三级", "value": "YJ_LEVEL3", "py": 9},
    {"label": "全部", "value": "ALL", "py": 255},
]

SORT_BY_OPTS = [
    {"label": "涨跌幅%", "value": "change_pct", "py": "change_pct"},
    {"label": "成交额", "value": "amount", "py": "amount"},
    {"label": "主力净流入", "value": "main_net_amount", "py": "main_net_amount"},
    {"label": "成交量", "value": "vol", "py": "vol"},
]

ASC_OPTS = [
    {"label": "降序", "value": "desc", "py": False},
    {"label": "升序", "value": "asc", "py": True},
]

# SortType 枚举（整数值，供 get_board_members / get_board_summary 使用）
SORT_TYPE_OPTS = [
    {"label": "代码", "value": "code", "py": 0},
    {"label": "名称", "value": "name", "py": 1},
    {"label": "涨跌幅%", "value": "change_pct", "py": 14},
    {"label": "振幅%", "value": "amplitude_pct", "py": 15},
    {"label": "市盈率TTM", "value": "pe_ttm", "py": 48},
    {"label": "主力净流入", "value": "main_net_amount", "py": 56},
    {"label": "成交量", "value": "volume", "py": 9},
    {"label": "成交额", "value": "total_amount", "py": 10},
]

# SortOrder 枚举（整数值）
SORT_ORDER_OPTS = [
    {"label": "降序", "value": "desc", "py": 1},
    {"label": "升序", "value": "asc", "py": 2},
]

BAR_TIME_OPTS = [
    {"label": "开始时间", "value": "start", "py": "start"},
    {"label": "结束时间", "value": "end", "py": "end"},
]

BLOCK_FILE_OPTS = [
    {"label": "行业/指数板块", "value": "block_zs.dat", "py": "block_zs.dat"},
    {"label": "概念板块", "value": "block_gn.dat", "py": "block_gn.dat"},
    {"label": "风格板块", "value": "block_fg.dat", "py": "block_fg.dat"},
]

SCOPE_OPTS = [
    {"label": "Tdx 行情主机", "value": "tdx", "py": "tdx"},
    {"label": "Mac 行情主机", "value": "mac", "py": "mac"},
    {"label": "两者", "value": "all", "py": "all"},
]


def p(key, label, type_, required=False, default=None, options=None, placeholder="",
       help="", minv=None, maxv=None, step=None):
    """构造单个参数 schema。"""
    return {
        "key": key, "label": label, "type": type_, "required": required,
        "default": default, "options": options or None, "placeholder": placeholder,
        "help": help, "min": minv, "max": maxv, "step": step,
    }


# ----------------------------------------------------------------------------
# 功能分组
# ----------------------------------------------------------------------------
GROUPS = [
    {"id": "conn", "label": "连接与主机", "icon": "database"},
    {"id": "market", "label": "行情信息", "icon": "list"},
    {"id": "kline", "label": "K线", "icon": "bar-chart"},
    {"id": "minute", "label": "分时", "icon": "clock"},
    {"id": "transaction", "label": "逐笔成交", "icon": "activity"},
    {"id": "finance", "label": "财务与除权", "icon": "file-text"},
    {"id": "block", "label": "板块文件", "icon": "layers"},
    {"id": "fundflow", "label": "资金流", "icon": "trending-up"},
    {"id": "file", "label": "文件下载", "icon": "download"},
    {"id": "macquote", "label": "Mac 行情", "icon": "activity"},
    {"id": "mackline", "label": "Mac K线", "icon": "bar-chart"},
    {"id": "mactick", "label": "Mac 分时/Tick", "icon": "candles"},
    {"id": "macboard", "label": "Mac 板块", "icon": "layers"},
    {"id": "maccapital", "label": "Mac 资金", "icon": "coins"},
    {"id": "macmonitor", "label": "Mac 监控", "icon": "eye"},
    {"id": "ex", "label": "扩展行情", "icon": "globe"},
    {"id": "cninfo", "label": "巨潮资讯", "icon": "book"},
    {"id": "chanlun", "label": "缠论分析", "icon": "candles"},
    {"id": "backtest", "label": "策略回测", "icon": "cpu"},
]

# ----------------------------------------------------------------------------
# 功能列表（覆盖 easy-tdx 全部对外接口）
# ----------------------------------------------------------------------------
FUNCTIONS = [
    # ---------------- 连接与主机 ----------------
    {
        "id": "ping", "group": "conn", "label": "主机延迟探测", "client": "ping",
        "method": "ping_all", "result": "table", "long": False,
        "params": [p("scope", "探测范围", "enum", required=True, default="tdx", options=SCOPE_OPTS,
                     help="测试通达信行情/扩展/Mac 主机的可达性与延迟")],
    },
    {
        "id": "hosts_info", "group": "conn", "label": "当前主机配置", "client": "host",
        "method": "info", "result": "table", "long": False,
        "params": [],
    },
    {
        "id": "host_refresh", "group": "conn", "label": "刷新最优主机", "client": "host",
        "method": "refresh", "result": "message", "long": True,
        "params": [p("which", "主机类型", "enum", required=True, default="tdx", options=SCOPE_OPTS,
                     help="重新 ping 所有候选主机并保存延迟最低者")],
    },
    {
        "id": "mac_server_info", "group": "conn", "label": "Mac 服务器信息", "client": "mac",
        "method": "get_server_info", "result": "table", "long": False, "params": [],
    },

    # ---------------- 行情信息 ----------------
    {
        "id": "security_count", "group": "market", "label": "证券总数", "client": "tdx",
        "method": "get_security_count", "result": "message", "long": False,
        "params": [p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS)],
    },
    {
        "id": "security_list", "group": "market", "label": "证券列表(分页)", "client": "tdx",
        "method": "get_security_list", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("start", "起始偏移", "number", required=True, default=0, minv=0, step=1),
        ],
    },
    {
        "id": "security_list_all", "group": "market", "label": "沪深A股全列表", "client": "tdx",
        "method": "get_security_list_all", "result": "table", "long": True,
        "params": [p("pages", "拉取页数", "text", required=False, default="all",
                     placeholder="all 或全部，或整数 N（每市场 N 页）")],
    },
    {
        "id": "security_quotes", "group": "market", "label": "实时五档行情", "client": "tdx",
        "method": "get_security_quotes", "result": "table", "long": False,
        "params": [p("stocks", "股票列表", "stocklist", required=True, default="SH 600519\nSZ 000858",
                     placeholder="每行一只：市场 代码，如 SH 600519")],
    },
    {
        "id": "market_stat", "group": "market", "label": "全市场涨跌统计", "client": "tdx",
        "method": "get_market_stat", "result": "table", "long": True,
        "params": [],
    },
    {
        "id": "price_limits", "group": "market", "label": "涨跌停价计算", "client": "tdx",
        "method": "get_price_limits", "result": "message", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("name", "名称", "text", required=True, default="贵州茅台"),
            p("pre_close", "昨收价", "number", required=True, default=1509.0, step=0.01),
        ],
    },

    # ---------------- K线 ----------------
    {
        "id": "security_bars", "group": "kline", "label": "个股K线", "client": "tdx",
        "method": "get_security_bars", "result": "table", "chart": "candle", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("category", "周期", "enum", required=True, default="DAY", options=KL_OPTS),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=100, minv=1, maxv=800, step=1),
            p("bar_time", "时间语义", "enum", required=False, default="start", options=BAR_TIME_OPTS),
        ],
    },
    {
        "id": "index_bars", "group": "kline", "label": "指数K线", "client": "tdx",
        "method": "get_index_bars", "result": "table", "chart": "candle", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="000001"),
            p("category", "周期", "enum", required=True, default="DAY", options=KL_OPTS),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=100, minv=1, maxv=800, step=1),
            p("bar_time", "时间语义", "enum", required=False, default="start", options=BAR_TIME_OPTS),
        ],
    },

    # ---------------- 分时 ----------------
    {
        "id": "minute_time_data", "group": "minute", "label": "当日分时", "client": "tdx",
        "method": "get_minute_time_data", "result": "table", "chart": "line", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "history_minute_time_data", "group": "minute", "label": "历史分时", "client": "tdx",
        "method": "get_history_minute_time_data", "result": "table", "chart": "line", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("date", "日期", "dateint", required=True, default="", placeholder="YYYYMMDD，如 20250601"),
        ],
    },

    # ---------------- 逐笔成交 ----------------
    {
        "id": "transaction_data", "group": "transaction", "label": "当日逐笔成交", "client": "tdx",
        "method": "get_transaction_data", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=200, minv=1, maxv=800, step=1),
        ],
    },
    {
        "id": "history_transaction_data", "group": "transaction", "label": "历史逐笔成交", "client": "tdx",
        "method": "get_history_transaction_data", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("date", "日期", "dateint", required=True, default="", placeholder="YYYYMMDD"),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=200, minv=1, maxv=800, step=1),
        ],
    },

    # ---------------- 财务与除权 ----------------
    {
        "id": "xdxr_info", "group": "finance", "label": "除权除息", "client": "tdx",
        "method": "get_xdxr_info", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "finance_info", "group": "finance", "label": "最新财务数据", "client": "tdx",
        "method": "get_finance_info", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "company_info_category", "group": "finance", "label": "公司信息目录", "client": "tdx",
        "method": "get_company_info_category", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "company_info_content", "group": "finance", "label": "公司信息文本", "client": "tdx",
        "method": "get_company_info_content", "result": "message", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("filename", "文件名", "text", required=True, default="csrc.dat",
              help="来自『公司信息目录』的 filename 字段"),
            p("offset", "偏移", "number", required=True, default=0, minv=0, step=1),
            p("length", "长度", "number", required=True, default=1024, minv=1, step=1),
        ],
    },
    {
        "id": "financial_file_list", "group": "finance", "label": "财报文件列表", "client": "tdx",
        "method": "get_financial_file_list", "result": "table", "long": True,
        "params": [p("host", "计算服务器", "text", required=False, default="",
                     placeholder="留空用默认计算服务器")],
    },
    {
        "id": "financial_records", "group": "finance", "label": "财报记录解析", "client": "tdx",
        "method": "get_financial_records", "result": "table", "long": True,
        "params": [
            p("filename", "财报文件", "text", required=True, default="tdxfin/gpcw20260331.zip",
              help="如 tdxfin/gpcw20260331.zip"),
            p("host", "计算服务器", "text", required=False, default="", placeholder="留空用默认"),
        ],
    },

    # ---------------- 板块文件 ----------------
    {
        "id": "block_info", "group": "block", "label": "板块成分解析", "client": "tdx",
        "method": "get_block_info", "result": "table", "long": False,
        "params": [p("filename", "板块文件", "enum", required=True, default="block_zs.dat",
                     options=BLOCK_FILE_OPTS)],
    },

    # ---------------- 资金流 ----------------
    {
        "id": "fund_flow", "group": "fundflow", "label": "当日资金流向", "client": "tdx",
        "method": "get_fund_flow", "result": "table", "chart": "fund", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "history_fund_flow", "group": "fundflow", "label": "历史资金流向", "client": "tdx",
        "method": "get_history_fund_flow", "result": "table", "chart": "fund", "long": True,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=30, minv=1, maxv=800, step=1),
        ],
    },

    # ---------------- 文件下载 ----------------
    {
        "id": "report_file", "group": "file", "label": "下载服务器文件", "client": "tdx",
        "method": "get_report_file", "result": "file", "long": True,
        "params": [p("filename", "文件名", "text", required=True, default="tdxhy.cfg",
                     help="如 tdxhy.cfg / base_info.zip")],
    },

    # ---------------- Mac 行情 ----------------
    {
        "id": "mac_stock_quotes", "group": "macquote", "label": "Mac 批量报价", "client": "mac",
        "method": "get_stock_quotes", "result": "table", "long": False,
        "params": [p("stocks", "股票列表", "stocklist", required=True, default="SH 600519\nSZ 000858",
                     placeholder="每行一只：市场 代码")],
    },
    {
        "id": "mac_stock_quotes_list", "group": "macquote", "label": "Mac 分类报价榜", "client": "mac",
        "method": "get_stock_quotes_list", "result": "table", "long": False,
        "params": [
            p("category", "市场分类", "enum", required=True, default="A", options=[
                {"label": "全部A股", "value": "A", "py": 6},
                {"label": "上证A", "value": "SH", "py": 0},
                {"label": "深证A", "value": "SZ", "py": 2},
                {"label": "科创板", "value": "KCB", "py": 8},
                {"label": "北证A", "value": "BJ", "py": 12},
                {"label": "创业板", "value": "CYB", "py": 14},
            ]),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=80, minv=1, maxv=500, step=1),
        ],
    },

    # ---------------- Mac K线 ----------------
    {
        "id": "mac_stock_kline", "group": "mackline", "label": "Mac K线", "client": "mac",
        "method": "get_stock_kline", "result": "table", "chart": "candle", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("period", "周期", "enum", required=True, default="DAILY", options=PERIOD_OPTS),
            p("count", "数量", "number", required=False, default=200, minv=1, maxv=3000, step=1),
            p("times", "周期倍数", "number", required=False, default=1, minv=1, maxv=30, step=1),
            p("adjust", "复权", "enum", required=False, default="NONE", options=ADJUST_OPTS),
            p("bar_time", "时间语义", "enum", required=False, default="start", options=BAR_TIME_OPTS),
        ],
    },
    {
        "id": "mac_stock_kline_indicators", "group": "mackline", "label": "Mac K线+指标", "client": "mac",
        "method": "get_stock_kline_with_indicators", "result": "table", "chart": "candle", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("indicators", "指标(逗号)", "text", required=False, default="MA,MACD,BOLL",
              help="如 MA,MACD,BOLL,KDJ"),
            p("period", "周期", "enum", required=False, default="DAILY", options=PERIOD_OPTS),
            p("count", "数量", "number", required=False, default=120, minv=1, maxv=1000, step=1),
            p("adjust", "复权", "enum", required=False, default="QFQ", options=ADJUST_OPTS),
        ],
    },
    {
        "id": "mac_kline_offset", "group": "mackline", "label": "Mac K线偏移量", "client": "mac",
        "method": "get_kline_offset", "result": "table", "long": True,
        "params": [
            p("offset", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=128000, minv=1, maxv=200000, step=1000),
        ],
    },

    # ---------------- Mac 分时/Tick ----------------
    {
        "id": "mac_tick_chart", "group": "mactick", "label": "Mac 分笔图", "client": "mac",
        "method": "get_tick_chart", "result": "table", "chart": "tick", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "mac_tick_charts", "group": "mactick", "label": "Mac 多日分笔", "client": "mac",
        "method": "get_tick_charts", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "mac_chart_sampling", "group": "mactick", "label": "Mac 抽样数据", "client": "mac",
        "method": "get_chart_sampling", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "mac_transactions", "group": "mactick", "label": "Mac 逐笔成交", "client": "mac",
        "method": "get_transactions", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("count", "数量", "number", required=False, default=2000, minv=1, maxv=20000, step=1),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("date", "日期(可选)", "dateint", required=False, default="",
              placeholder="留空=今天，否则 YYYYMMDD"),
        ],
    },
    {
        "id": "mac_symbol_info", "group": "mactick", "label": "Mac 个股快照", "client": "mac",
        "method": "get_symbol_info", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },

    # ---------------- Mac 板块 ----------------
    {
        "id": "mac_board_list", "group": "macboard", "label": "板块列表", "client": "mac",
        "method": "get_board_list", "result": "table", "long": True,
        "params": [p("board_type", "板块类型", "enum", required=True, default="HY", options=BOARD_OPTS)],
    },
    {
        "id": "mac_board_members", "group": "macboard", "label": "板块成分股", "client": "mac",
        "method": "get_board_members", "result": "table", "long": True,
        "params": [
            p("board_symbol", "板块代码", "text", required=True, default="881001",
              help="如行业 881001 / 概念 885001"),
            p("count", "数量", "number", required=False, default=1000, minv=1, maxv=100000, step=100),
            p("sort_type", "排序字段", "enum", required=False, default="change_pct", options=SORT_TYPE_OPTS),
            p("sort_order", "排序方向", "enum", required=False, default="desc", options=SORT_ORDER_OPTS),
        ],
    },
    {
        "id": "mac_belong_board", "group": "macboard", "label": "所属板块", "client": "mac",
        "method": "get_belong_board", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "mac_board_summary", "group": "macboard", "label": "板块概况", "client": "mac",
        "method": "get_board_summary", "result": "json", "long": False,
        "params": [
            p("board_symbol", "板块代码", "text", required=True, default="881001"),
            p("sort_type", "排序字段", "enum", required=False, default="change_pct", options=SORT_TYPE_OPTS),
            p("sort_order", "排序方向", "enum", required=False, default="desc", options=SORT_ORDER_OPTS),
        ],
    },
    {
        "id": "mac_board_ranking", "group": "macboard", "label": "板块涨幅榜", "client": "mac",
        "method": "get_board_ranking", "result": "table", "chart": "line", "long": True,
        "params": [
            p("board_type", "板块类型", "enum", required=True, default="HY", options=BOARD_OPTS),
            p("top_n", "聚合上限", "number", required=False, default=50, minv=1, maxv=400, step=1),
            p("sort_by", "排序字段", "enum", required=False, default="change_pct", options=SORT_BY_OPTS),
            p("ascending", "升序", "enum", required=False, default="desc", options=ASC_OPTS),
        ],
    },
    {
        "id": "mac_board_change_ranking", "group": "macboard", "label": "板块N日涨幅榜", "client": "mac",
        "method": "get_board_change_ranking", "result": "table", "chart": "line", "long": True,
        "params": [
            p("board_type", "板块类型", "enum", required=True, default="HY", options=BOARD_OPTS),
            p("target_date", "截止日期", "dateint", required=False, default="",
              placeholder="留空=最新交易日 YYYYMMDD"),
            p("days", "回溯交易日", "number", required=False, default=20, minv=1, maxv=250, step=1),
            p("top_n", "返回数量", "number", required=False, default=50, minv=1, maxv=400, step=1),
            p("ascending", "升序", "enum", required=False, default="desc", options=ASC_OPTS),
        ],
    },

    # ---------------- Mac 资金 ----------------
    {
        "id": "mac_capital_flow", "group": "maccapital", "label": "Mac 资金流向", "client": "mac",
        "method": "get_capital_flow", "result": "table", "chart": "fund", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },

    # ---------------- Mac 监控 ----------------
    {
        "id": "mac_auction", "group": "macmonitor", "label": "集合竞价", "client": "mac",
        "method": "get_auction", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "mac_unusual", "group": "macmonitor", "label": "异动监控", "client": "mac",
        "method": "get_unusual", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=100, minv=1, maxv=10000, step=100),
        ],
    },

    # ---------------- 扩展行情 ----------------
    {
        "id": "ex_markets", "group": "ex", "label": "扩展市场列表", "client": "ex",
        "method": "get_markets", "result": "table", "long": False, "params": [],
    },
    {
        "id": "ex_instrument_count", "group": "ex", "label": "扩展商品总数", "client": "ex",
        "method": "get_instrument_count", "result": "message", "long": False, "params": [],
    },
    {
        "id": "ex_instrument_info", "group": "ex", "label": "扩展商品信息", "client": "ex",
        "method": "get_instrument_info", "result": "table", "long": False,
        "params": [
            p("start", "起始偏移", "number", required=True, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=100, minv=1, maxv=1000, step=1),
        ],
    },
    {
        "id": "ex_instrument_quote", "group": "ex", "label": "扩展五档行情", "client": "ex",
        "method": "get_instrument_quote", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "ex_instrument_quote_list", "group": "ex", "label": "扩展行情列表", "client": "ex",
        "method": "get_instrument_quote_list", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("category", "类别", "enum", required=True, default="A", options=[
                {"label": "全部A股", "value": "A", "py": 6},
                {"label": "上证A", "value": "SH", "py": 0},
                {"label": "深证A", "value": "SZ", "py": 2},
                {"label": "科创板", "value": "KCB", "py": 8},
                {"label": "北证A", "value": "BJ", "py": 12},
                {"label": "创业板", "value": "CYB", "py": 14},
            ]),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=80, minv=1, maxv=200, step=1),
        ],
    },
    {
        "id": "ex_instrument_bars", "group": "ex", "label": "扩展K线", "client": "ex",
        "method": "get_instrument_bars", "result": "table", "chart": "candle", "long": False,
        "params": [
            p("category", "类别", "enum", required=True, default="A", options=[
                {"label": "全部A股", "value": "A", "py": 6},
                {"label": "上证A", "value": "SH", "py": 0},
                {"label": "深证A", "value": "SZ", "py": 2},
                {"label": "科创板", "value": "KCB", "py": 8},
                {"label": "北证A", "value": "BJ", "py": 12},
                {"label": "创业板", "value": "CYB", "py": 14},
            ]),
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=200, minv=1, maxv=700, step=1),
            p("bar_time", "时间语义", "enum", required=False, default="start", options=BAR_TIME_OPTS),
        ],
    },
    {
        "id": "ex_history_instrument_bars_range", "group": "ex", "label": "扩展历史K线(区间)", "client": "ex",
        "method": "get_history_instrument_bars_range", "result": "table", "chart": "candle", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("start_date", "起始日期", "dateint", required=True, default="", placeholder="YYYYMMDD"),
            p("end_date", "结束日期", "dateint", required=True, default="", placeholder="YYYYMMDD"),
            p("bar_time", "时间语义", "enum", required=False, default="start", options=BAR_TIME_OPTS),
        ],
    },
    {
        "id": "ex_minute_time_data", "group": "ex", "label": "扩展当日分时", "client": "ex",
        "method": "get_minute_time_data", "result": "table", "chart": "line", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
        ],
    },
    {
        "id": "ex_history_minute_time_data", "group": "ex", "label": "扩展历史分时", "client": "ex",
        "method": "get_history_minute_time_data", "result": "table", "chart": "line", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("date", "日期", "dateint", required=True, default="", placeholder="YYYYMMDD"),
        ],
    },
    {
        "id": "ex_transaction_data", "group": "ex", "label": "扩展当日分笔", "client": "ex",
        "method": "get_transaction_data", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=1800, minv=1, maxv=5000, step=1),
        ],
    },
    {
        "id": "ex_history_transaction_data", "group": "ex", "label": "扩展历史分笔", "client": "ex",
        "method": "get_history_transaction_data", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("date", "日期", "dateint", required=True, default="", placeholder="YYYYMMDD"),
            p("start", "起始偏移", "number", required=False, default=0, minv=0, step=1),
            p("count", "数量", "number", required=False, default=1800, minv=1, maxv=5000, step=1),
        ],
    },

    # ---------------- 巨潮资讯 ----------------
    {
        "id": "cninfo_announcements", "group": "cninfo", "label": "公告列表", "client": "cninfo",
        "method": "get_announcements", "result": "table", "long": False,
        "params": [
            p("code", "6位代码", "text", required=True, default="600519",
              help="不含市场前缀，如 688017"),
            p("count", "每页数量", "number", required=False, default=30, minv=1, maxv=100, step=1),
            p("page", "页码", "number", required=False, default=1, minv=1, step=1),
        ],
    },
    {
        "id": "cninfo_download_pdf", "group": "cninfo", "label": "下载公告PDF", "client": "cninfo",
        "method": "download_pdf", "result": "file", "long": True,
        "params": [
            p("code", "6位代码", "text", required=True, default="600519"),
            p("index", "公告序号", "number", required=True, default=0, minv=0, step=1,
              help="先查询公告列表，取第 N 条（从 0 开始）"),
        ],
    },

    # ---------------- 缠论分析 ----------------
    {
        "id": "chanlun_analyze", "group": "chanlun", "label": "缠论笔段中枢", "client": "chanlun",
        "method": "analyze", "result": "table", "long": False,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("period", "周期", "enum", required=True, default="DAILY", options=PERIOD_OPTS),
            p("count", "K线条数", "number", required=False, default=300, minv=10, maxv=2000, step=1),
            p("adjust", "复权", "enum", required=False, default="QFQ", options=ADJUST_OPTS),
        ],
    },

    # ---------------- 策略回测 ----------------
    {
        "id": "backtest_run", "group": "backtest", "label": "运行策略回测", "client": "backtest",
        "method": "run", "result": "table", "chart": "equity", "long": True,
        "params": [
            p("market", "市场", "enum", required=True, default="SH", options=MARKET_OPTS),
            p("code", "代码", "text", required=True, default="600519"),
            p("period", "周期", "enum", required=True, default="DAILY", options=PERIOD_OPTS),
            p("count", "K线条数", "number", required=False, default=500, minv=50, maxv=3000, step=1),
            p("adjust", "复权", "enum", required=False, default="QFQ", options=ADJUST_OPTS),
            p("strategy", "策略", "strategy", required=True, default="",
              help="从回测注册表选择内置策略"),
            p("cash", "初始资金", "number", required=False, default=100000, minv=1000, step=1000),
        ],
    },
]


# 便捷查询
def get_function(func_id: str) -> dict | None:
    for f in FUNCTIONS:
        if f["id"] == func_id:
            return f
    return None


def get_groups_with_functions() -> list[dict]:
    """返回分组及其下功能（供前端渲染导航）。"""
    out = []
    for g in GROUPS:
        funcs = [f for f in FUNCTIONS if f["group"] == g["id"]]
        if funcs:
            out.append({**g, "functions": funcs})
    return out
