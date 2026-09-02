#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""东方财富事实层 —— 端点常量与字段映射（集中管理，便于契约测试与维护）

所有端点均为页面公开、免鉴权的裸 HTTP JSON 接口。2026-08-07 实测结论：

| 集群            | 状态   | 说明                                                     |
|-----------------|--------|----------------------------------------------------------|
| datacenter-web  | 稳定   | 无限流，支持分页/过滤，事实层主力数据源                   |
| push2ex         | 稳定   | 涨停/跌停/炸板池，独立集群，不受 push2 限流影响           |
| push2 / push2his| 限流   | 按 IP 全集群配额，换主机无效；仅作可选增强，必须可降级     |
| clist           | 限流   | 已被本机 IP 拉黑，仅保留常量，默认不使用                  |

设计原则（本次重构确立）：
    事实层的**每一项核心指标都必须有 datacenter 主链路**，push2 家族只做锦上添花。
    这样即便本机 IP 处于限流惩罚期，盘后快照依然能产出完整数据。

合规底线：仅限个人学习与技术研究，遵守 robots 与频率限制，勿商用分发原始数据。
"""

from typing import Dict, List

# 主机 -> Referer（免检关键，client 自动注入）
HOST_REFERER: Dict[str, str] = {
    "push2.eastmoney.com": "https://quote.eastmoney.com/",
    "push2delay.eastmoney.com": "https://quote.eastmoney.com/",
    "push2his.eastmoney.com": "https://quote.eastmoney.com/",
    "push2ex.eastmoney.com": "https://quote.eastmoney.com/ztb/detail",
    "datacenter-web.eastmoney.com": "https://data.eastmoney.com/",
    "datacenter.eastmoney.com": "https://data.eastmoney.com/",
    "emweb.securities.eastmoney.com": "https://emweb.securities.eastmoney.com/",
    "np-anotice-stock.eastmoney.com": "https://data.eastmoney.com/notices/",
    "np-listapi.eastmoney.com": "https://kuaixun.eastmoney.com/",
    "reportapi.eastmoney.com": "https://data.eastmoney.com/report/",
    "data.10jqka.com.cn": "https://data.10jqka.com.cn/mobile/limitup/v2/index.html",
}

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 端点组 -> 限速（最小请求间隔秒）
# push2 家族本机处于 IP 惩罚期，间隔调大以避免滑动窗口被持续续期。
GROUP_MIN_INTERVAL: Dict[str, float] = {
    "em_push2": 1.5,        # 限流敏感，降频
    "em_push2his": 1.5,     # 限流敏感，降频
    "em_push2delay": 1.0,   # 延时集群，push2 断连时的降级主机
    "em_push2ex": 0.6,      # 独立集群，正常
    "em_datacenter": 0.35,  # 无限流，主力链路
    "em_emweb": 1.0,
    "em_reportapi": 1.0,
    "em_nplist": 1.0,
    "em_clist": 10.0,       # 已被拉黑，仅降级备用
    "ths": 0.8,             # 同花顺涨停聚焦：单客户端全局串行约 1.25 req/s，留足余量
}

# 端点组 -> 熔断注册名（写入 source_health 表）
GROUP_SOURCE_NAME: Dict[str, str] = {g: g for g in GROUP_MIN_INTERVAL}

# 连续网络级失败达到该阈值后，整组进入冷却期，期间直接短路不再发请求。
# 目的：东财限流是「滑动窗口」，惩罚期内继续探测会不断续期，必须彻底静默。
GROUP_COOLDOWN_THRESHOLD: Dict[str, int] = {
    "em_push2": 3,
    "em_push2his": 3,
    "em_push2delay": 4,
    "em_push2ex": 5,
    "em_datacenter": 8,
    "ths": 3,                # 同花顺：连续 3 次网络失败即冷却，避免被持续限流/断连
}
GROUP_COOLDOWN_SECONDS: Dict[str, float] = {
    "em_push2": 600.0,
    "em_push2his": 600.0,
    "em_push2delay": 300.0,
    "em_push2ex": 120.0,
    "em_datacenter": 60.0,
    "ths": 300.0,            # 同花顺冷却 5 分钟：限流是滑动窗口，惩罚期继续探测会续期
}
DEFAULT_COOLDOWN_THRESHOLD = 5
DEFAULT_COOLDOWN_SECONDS = 120.0

# 网络级失败不重试的端点组（重试只会加重限流）
NO_RETRY_GROUPS = {"em_push2", "em_push2his", "em_push2delay", "em_clist"}

# datacenter 报表名（全部经 2026-08-07 实测 success=true）
RP_F10_BASIC_ORGINFO = "RPT_F10_BASIC_ORGINFO"        # 全量证券名录（含新三板，需过滤）
RP_F10_CORETHEME = "RPT_F10_CORETHEME_BOARDTYPE"      # 个股↔核心题材板块
RP_DAILYBILLBOARD = "RPT_DAILYBILLBOARD_DETAILSNEW"   # 龙虎榜明细
RP_MAINFUND = "RPT_DMSK_TS_STOCKNEW"                  # 个股资金流（全市场，pageSize 上限 500）
RP_VALUATION = "RPT_VALUEANALYSIS_DET"                # 估值分析（全市场日频，判定在市标的）
RP_RZRQ_DETAIL = "RPTA_WEB_RZRQ_GGMX"                 # 融资融券个股明细
RP_OP_PREDICT = "RPT_PUBLIC_OP_PREDICT"               # 业绩预告
RP_IPO_APPLY = "RPTA_APP_IPOAPPLY"                    # 新股申购日历

# 各报表的服务端 pageSize 上限（超限会被**静默截断**，必须按此分页）
# 数值均为 2026-08-07 实测；client.datacenter_pages 具备截断自愈，
# 但登记正确值可省掉一次探测请求。
RP_PAGE_SIZE: Dict[str, int] = {
    RP_MAINFUND: 500,           # 实测：请求 5000 只回 500
    RP_VALUATION: 5000,         # 实测：精简列 5000 可用；columns=ALL 会回「服务器繁忙」
    RP_F10_BASIC_ORGINFO: 5000,
    RP_F10_CORETHEME: 5000,
    RP_DAILYBILLBOARD: 500,     # 单日仅数十条，取保守值
    RP_RZRQ_DETAIL: 500,        # 实测：请求 5000 只回 500（曾误记为 5000，导致丢 88% 数据）
    RP_OP_PREDICT: 500,         # 实测：请求 5000 只回 500
    RP_IPO_APPLY: 5000,         # 实测：5000 可用
}
DEFAULT_PAGE_SIZE = 500

# 分页器页数硬上限。防止报表 count 为全历史规模（如 RPT_VALUEANALYSIS_DET
# count=934 万）时，pageSize 自愈逻辑把页数放大到上千页而打爆采集。
HARD_PAGE_CAP = 60

# 基础 URL
DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
PUSH2 = "https://push2.eastmoney.com/api/qt"
PUSH2EX = "https://push2ex.eastmoney.com"
PUSH2HIS = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
PUSH2HIS_FFLOW = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
# 分时（当日/近 N 日 每分钟 价+均价），与 kline 数据结构不同，独立端点
PUSH2HIS_TRENDS = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"

# 延时行情集群。2026-08-07 实测：在 push2/push2his 对本 IP 全部断连（限流）时，
# push2delay 仍返回 HTTP 200 且数据正确（f43 收盘价与 datacenter 快照一致）。
# ⚠️ 能力边界：**只提供快照，不提供历史 K 线**（kline/get 恒返回
#    dktotal=0、klines=[]），因此仅可作为 push2 stock/get 的降级主机，
#    不能替代 push2his 的日线链路。
PUSH2_DELAY = "https://push2delay.eastmoney.com/api/qt"
EMWEB_F10 = "https://emweb.securities.eastmoney.com/PC_HSF10"
NP_ANOTICE = "https://np-anotice-stock.eastmoney.com/api/security/ann"
NP_LISTAPI = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
REPORTAPI = "https://reportapi.eastmoney.com/report/list"

# 公开常量（页面 JS 中的 ut），非私密 token
UT = "fa5fd1943c7b386f172d6893dbfba10b"
# push2ex 涨停/跌停/炸板池专用 ut（32 位）。
# ⚠️ 历史缺陷：此常量曾被误写成 26 位截断值，导致 push2ex 恒返回 rc=205、
#    limit_pool 表长期为空。实测：32 位 -> rc=0 tc=79；26 位 -> rc=205 pool=0。
UT_TOPIC = "7eea3edcaed734bea9cbfc24409ed989"

# 市场宽度备用源（push2 ulist）。
# ⚠️ 语义缺陷：399001 深证成指仅 500 只成分股，且创业板/科创板是深证/上证的子集，
#    四个指数相加会重复计数。此路径已降级为「参考值」，主链路见 quote.fetch_market_breadth。
BREADTH_INDEX_SECIds: List[str] = ["1.000001", "0.399001"]
BREADTH_FIELDS = "f12,f14,f104,f105,f106,f2,f3"

# 证券类型判别（RPT_F10_BASIC_ORGINFO.SECURITY_TYPE）
# 实测全量 24759 条分布：新三板 15966 / 老三板 313 / B股 115 / CDR 8 / A股 8357
A_SHARE_TYPES = (
    "上交所主板A股", "上交所科创板A股", "上交所风险警示板A股",
    "深交所主板A股", "深交所创业板A股", "深交所风险警示板A股",
    "北京证券交易所A股",
)
# 板块归类：SECURITY_TYPE -> board
BOARD_OF_TYPE: Dict[str, str] = {
    "上交所主板A股": "主板",
    "深交所主板A股": "主板",
    "上交所科创板A股": "科创板",
    "深交所创业板A股": "创业板",
    "北京证券交易所A股": "北交所",
    "上交所风险警示板A股": "风险警示",
    "深交所风险警示板A股": "风险警示",
}


def is_a_share(security_type: str) -> bool:
    """仅保留 A 股（含风险警示板与北交所），剔除新三板/老三板/B股/CDR。"""
    return (security_type or "").strip() in A_SHARE_TYPES


# secid 规则：代码 -> "市场.代码"
# 沪市(600/601/603/605/688/689) -> 1 ；深市(000/001/002/003/300/301) -> 0
# 北交所(4*/8*/92*)             -> 0（东财 push2 对北交所使用 0 前缀）
_SH_PREFIX = ("600", "601", "603", "605", "688", "689")
_SZ_PREFIX = ("000", "001", "002", "003", "300", "301")


def secid_of(code: str) -> str:
    """6 位代码 -> 东财 secid（市场.代码）"""
    code = (code or "").strip()
    if not code:
        return ""
    if "." in code:  # 已是 secu 格式 000001.SZ -> 转成 secid
        m, c = code.split(".", 1)
        return f"{'1' if m.upper() == 'SH' else '0'}.{c}"
    if code[:3] in _SH_PREFIX or code[0] == "6":
        return f"1.{code}"
    if code[:3] in _SZ_PREFIX or code[0] in ("0", "3"):
        return f"0.{code}"
    if code[0] in ("8", "4", "9"):
        return f"0.{code}"
    return f"1.{code}"


def secid_of_secu(secu: str) -> str:
    """000001.SZ -> 0.000001"""
    if "." not in secu:
        return secid_of(secu)
    m, c = secu.split(".", 1)
    return f"{'1' if m.upper() == 'SH' else '0'}.{c}"


def compact_date(d: str) -> str:
    """'2026-08-07' -> '20260807'；已是紧凑格式则原样返回。

    ⚠️ 历史缺陷：kline.py 曾把带横杠日期直接塞进 push2his 的 beg 参数，
       东财对非法 beg 静默忽略并回吐 1991 年至今的全历史（单只 7000+ 根），
       导致全市场采集请求量放大 ~1400 倍，是本机 IP 被限流的直接诱因。
    """
    s = (d or "").strip().replace("-", "").replace("/", "")
    return s[:8]


def dash_date(d: str) -> str:
    """'20260807' 或 '2026-08-07 00:00:00' -> '2026-08-07'"""
    s = (d or "").strip()
    if not s:
        return ""
    s = s.split(" ")[0]
    if "-" in s:
        return s[:10]
    if len(s) >= 8:
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s


# push2 stock/get 字段映射（fltt=2 时价格已为元）
FUND_FIELDS = "f12,f14,f62,f184,f66,f72,f75,f78,f81,f84,f87,f160,f170,f43,f57"

# K 线 fields2：f51 日期 f52 开 f53 收 f54 高 f55 低 f56 量 f57 额
#               f58 振幅 f59 涨跌幅 f60 涨跌额 f61 换手
KLINE_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"

# 分时 trends2 字段：⚠️ 必须传完整字段集（实测短字段集会被服务器断连）。
# 行序（f51..f61）：f51 时间 f52 开 f53 当前价 f54 高 f55 低
#                  f56 成交量(手) f57 成交额 f58 均价 f59..f61 其他
# 解析时取：时间=p[0] 价格=p[2] 均价=p[7] 量=p[5]
TRENDS_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"

FLTT = 2
