#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富日历数据源配置

所有端点与参数均来自对官网前端 JS 的逆向：
  - 财经日历  data.eastmoney.com/newstatic/js/cjrl/default.js   -> RPT_CPH_FECALENDAR
  - 股市日历  data.eastmoney.com/newstatic/js/gsrl/default.js   -> RPT_SPECIAL_*
  - 新股日历  data.eastmoney.com/newstatic/js/xg/calendar.js    -> RPT_IPO_CALENDAR
  - 全球经济  forex.eastmoney.com/FC.html?Date=YYYY-MM-DD       -> 服务端渲染表格
"""

from typing import Dict, List

# 端点
EM_DATACENTER: str = "https://datacenter-web.eastmoney.com/api/data/v1/get"
EM_DATACENTER_SEC: str = "https://datacenter-web.eastmoney.com/securities/api/data/v1/get"
EM_FOREX_CALENDAR: str = "https://forex.eastmoney.com/FC.html"

# 东财 datacenter 单页硬上限为 500，超过无效（实测 pageSize=5000 仍只返回 500）
EM_PAGE_SIZE: int = 500
EM_MAX_PAGES: int = 20

PC_UA: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def datacenter_headers(referer: str = "https://data.eastmoney.com/") -> Dict[str, str]:
    return {
        "User-Agent": PC_UA,
        "Referer": referer,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def forex_headers() -> Dict[str, str]:
    return {
        "User-Agent": PC_UA,
        "Referer": "https://forex.eastmoney.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


# 日历类型
CAL_TYPES: Dict[str, Dict[str, str]] = {
    "finance": {
        "label": "财经日历",
        "icon": "calendar",
        "desc": "财经会议、重要经济数据发布、政策事件",
        "site": "https://data.eastmoney.com/cjrl/default.html",
    },
    "stock": {
        "label": "股市日历",
        "icon": "trending",
        "desc": "个股公司行为：分红转增、股东大会、增发配股、特别处理",
        "site": "https://data.eastmoney.com/gsrl/default.html",
    },
    "ipo": {
        "label": "新股日历",
        "icon": "sparkle",
        "desc": "新股与可转债的申购、中签、缴款、上市节点",
        "site": "https://data.eastmoney.com/xg/xg/calendar.html",
    },
    "global": {
        "label": "全球经济",
        "icon": "globe",
        "desc": "全球宏观经济数据公布：前值 / 预测值 / 公布值",
        "site": "https://forex.eastmoney.com/FC.html",
    },
}

CAL_TYPE_KEYS: List[str] = list(CAL_TYPES.keys())


# 财经日历：STD_TYPE_CODE -> 分类
FINANCE_TYPE_CODE_MAP: Dict[str, str] = {
    "1": "财经会议",
    "2": "重要经济数据",
    "3": "其它",
}

FINANCE_CATEGORIES: List[str] = ["财经会议", "重要经济数据", "其它"]

# 高优先级会议（提升重要性）
FINANCE_HIGH_TYPES = (
    "美联储议息会议",
    "国务院常务会议",
    "中央经济工作会议",
    "政治局会议",
    "欧洲央行议息会议",
)

FINANCE_COLUMNS: str = (
    "START_DATE,END_DATE,FE_CODE,FE_NAME,FE_TYPE,CONTENT,"
    "STD_TYPE_CODE,SPONSOR_NAME,CITY"
)


# 股市日历：EVENT_TYPE -> 分类（对应官网 6 个 Tab）
STOCK_CATEGORIES: List[str] = [
    "特别处理", "首发新股", "增发配股", "分红转增", "股东权益", "其它",
]

# 官网 reportName 映射（保留备用；实际抓取用 RPT_SPECIAL_ALL 一次取全集）
STOCK_REPORTS: Dict[str, str] = {
    "全部": "RPT_SPECIAL_ALL",
    "特别处理": "RPT_SPECIAL_SPDECISION",
    "首发新股": "RPT_SPECIAL_IPODECLAR",
    "增发配股": "RPT_SPECIAL_SEOALLOTMENT",
    "分红转增": "RPT_SPECIAL_DIVIDEND",
    "股东权益": "RPT_SPECIAL_HOLDERS",
}

STOCK_COLUMNS: str = (
    "SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,EVENT_TYPE,EVENT_CONTENT,TRADE_DATE"
)

# 分类判定规则（顺序敏感：先匹配先生效）
STOCK_CATEGORY_RULES = (
    (("特别处理", "*处理", "ST"), "特别处理"),
    (("首发", "中签"), "首发新股"),
    (("增发", "配股"), "增发配股"),
    (("分红", "转增", "派息", "除权除息", "红利"), "分红转增"),
    (("股东", "投票", "股权登记"), "股东权益"),
)

STOCK_CATEGORY_IMPORTANCE: Dict[str, int] = {
    "特别处理": 3,
    "首发新股": 3,
    "分红转增": 2,
    "增发配股": 2,
    "股东权益": 1,
    "其它": 1,
}


# 新股申购日历
IPO_CATEGORIES: List[str] = ["申购", "中签率", "中签号", "缴款日", "上市"]

IPO_IMPORTANCE: Dict[str, int] = {
    "申购": 3,
    "上市": 3,
    "缴款日": 2,
    "中签号": 2,
    "中签率": 2,
}

# SECURITY_TYPE: 0=新股 1=可转债
IPO_SECURITY_TYPE: Dict[str, str] = {"0": "新股", "1": "可转债"}


# 全球经济日历
GLOBAL_COUNTRIES: List[str] = [
    "中国", "美国", "德国", "瑞士", "日本", "英国",
    "澳大利亚", "欧盟", "欧元区", "加拿大", "中国香港",
]

GLOBAL_IMPORTANCE_MAP: Dict[str, int] = {"高": 3, "中": 2, "低": 1}

# FC.html 表头（实测）：
# 序号 | 公布日 | 时间 | 国家/地区 | 事件 | 报告期 | 公布值 | 预测值 | 前值 | 重要性 | 趋势
GLOBAL_COL_INDEX = {
    "seq": 0, "date": 1, "time": 2, "region": 3, "title": 4,
    "period": 5, "actual": 6, "forecast": 7, "prev": 8,
    "importance": 9, "trend": 10,
}


# 通用
IMPORTANCE_LABELS: Dict[int, str] = {0: "未知", 1: "低", 2: "中", 3: "高"}
