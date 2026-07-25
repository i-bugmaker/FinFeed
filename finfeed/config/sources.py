#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻源配置

所有新闻源的定义集中在此处，支持通过 Parser 类进行策略模式扩展。
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NewsSource:
    """新闻源数据类"""
    name: str
    url: str
    parser_type: str = "json"
    method: str = "GET"
    headers: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    verify_ssl: bool = True
    timeout: Optional[float] = None
    enabled: bool = True


# ============================================================
# 预定义的财经新闻源
# ============================================================
FINANCE_NEWS_SOURCES: list[NewsSource] = [
    NewsSource(
        name="新浪财经",
        url="https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num=15",
        parser_type="sina",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn/",
            "Accept": "application/json",
        },
    ),
    NewsSource(
        name="财联社",
        url="https://www.cls.cn/api/cache?app=CailianpressWeb&name=telegraph&os=web&sv=8.7.9",
        parser_type="cls",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.cls.cn/telegraph",
            "Accept": "application/json, text/plain, */*",
        },
    ),
    NewsSource(
        name="同花顺",
        url="https://news.10jqka.com.cn/tapp/news/push/stock",
        parser_type="ths",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "http://news.10jqka.com.cn/",
            "Accept": "application/json",
        },
        params={"page": 1, "tag": "", "type": "all"},
    ),
    NewsSource(
        name="同花顺原创",
        url="http://yuanchuang.10jqka.com.cn",
        parser_type="ths_yc",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "http://yuanchuang.10jqka.com.cn/",
            "Accept": "text/html",
        },
    ),
    NewsSource(
        name="东方财富",
        url="https://np-listapi.eastmoney.com/comm/web/getFastNewsList",
        parser_type="eastmoney",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://kuaixun.eastmoney.com/",
            "Accept": "application/json",
        },
        params={
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": "",
            "pageSize": 20,
        },
    ),
    NewsSource(
        name="雅虎财经",
        url="https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,AAPL,MSFT&region=US&lang=en-US",
        parser_type="rss",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
    ),
    NewsSource(
        name="21经济网",
        url="https://api.21jingji.com/timestream/getListweb?page=1",
        parser_type="jingji21",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.21jingji.com/",
            "Accept": "application/json",
        },
    ),
    NewsSource(
        name="华尔街见闻",
        url="https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&accept=article&limit=30",
        parser_type="wallstreetcn",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://wallstreetcn.com/",
            "Accept": "application/json",
        },
    ),
    NewsSource(
        name="金十数据",
        url="https://www.jin10.com/flash_newest.js",
        parser_type="jin10",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.jin10.com/",
            "Accept": "*/*",
        },
    ),
    NewsSource(
        name="格隆汇文章",
        url="https://www.gelonghui.com/news/",
        parser_type="gelonghui_article",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.gelonghui.com/",
            "Accept": "text/html",
        },
    ),
    NewsSource(
        name="格隆汇快讯",
        url="https://www.gelonghui.com/api/live-channels/all/lives/v4",
        parser_type="gelonghui_live",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.gelonghui.com/live",
            "Accept": "application/json",
        },
        params={"category": "all", "limit": 15},
    ),
    NewsSource(
        name="法布财经",
        url="https://api.fastbull.cn/fastbull-news-service/api/getNewsPageByTagIds",
        parser_type="fastbull",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.fastbull.cn/",
            "Accept": "application/json",
            "Origin": "https://www.fastbull.cn",
        },
        params={"pageNo": 1, "pageSize": 30},
    ),
    NewsSource(
        name="企查查",
        url="https://www.qcc.com/api/home/getNewsFlash?firstRankIndex=1&lastRankIndex=0&lastRankTime=&pageSize=30",
        parser_type="qcc",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.qcc.com/",
            "Accept": "application/json",
        },
    ),
    NewsSource(
        name="巨潮公告",
        url="https://www.cninfo.com.cn/new/hisAnnouncement/query",
        parser_type="cninfo",
        method="POST",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://www.cninfo.com.cn",
            "X-Requested-With": "XMLHttpRequest",
        },
        params={
            "pageNum": "1",
            "pageSize": "30",
            "column": "",
            "tabName": "fulltext",
            "plate": "",
            "stock": "",
            "searchkey": "",
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": "",
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        },
    ),
    NewsSource(
        name="cnBeta",
        url="https://rss.cnbeta.com.tw/",
        parser_type="rss",
        verify_ssl=False,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        },
    ),
    NewsSource(
        name="每经网",
        url="https://live.nbd.com.cn/",
        parser_type="nbd",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://live.nbd.com.cn/",
            "Accept": "text/html",
        },
    ),
    NewsSource(
        name="凤凰财经",
        url="https://finance.ifeng.com/",
        parser_type="ifeng",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://finance.ifeng.com/",
            "Accept": "text/html",
        },
    ),
    NewsSource(
        name="界面新闻",
        url="https://www.jiemian.com/",
        parser_type="jiemian",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.jiemian.com/",
            "Accept": "text/html",
        },
    ),
    NewsSource(
        name="澎湃新闻",
        url="https://www.thepaper.cn/",
        parser_type="thepaper",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.thepaper.cn/",
            "Accept": "text/html",
        },
    ),
    NewsSource(
        name="和讯网",
        url="https://stock.hexun.com/",
        parser_type="hexun",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://stock.hexun.com/",
            "Accept": "text/html",
        },
    ),
    NewsSource(
        name="第一财经",
        url="https://www.yicai.com/api/ajax/getbrieflist",
        parser_type="yicai",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.yicai.com/brief/",
            "Accept": "application/json",
        },
        params={"page": 1, "pagesize": 20, "id": 0},
    ),
    NewsSource(
        name="韭研公社",
        url="https://www.jiuyangongshe.com",
        parser_type="jiuyan",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.jiuyangongshe.com/",
            "Accept": "text/html",
        },
    ),
]

# ============================================================
# 舆情论坛数据源（UGC用户生成内容：散户讨论、情绪、观点）
# 重点区分财经新闻：这里全部是散户真实发言、讨论热度、情绪信号
# ============================================================
_MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
_PC_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def _mobile_headers(referer: str = "https://m.guba.eastmoney.com/") -> dict:
    return {
        "User-Agent": _MOBILE_UA,
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

def _pc_headers(referer: str) -> dict:
    return {
        "User-Agent": _PC_UA,
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

FORUM_SOURCES: list[NewsSource] = [
    # ---- 人气风向标 ----
    NewsSource(
        name="东财人气榜",
        url="https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
        parser_type="em_hot_rank",
        method="POST",
        headers={
            "User-Agent": _PC_UA,
            "Referer": "https://gubatop.eastmoney.com/",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        params={
            "appId": "appId01",
            "globalId": "786e4c21-70dc-435a-93bb-38",
            "marketType": "",
            "pageNo": 1,
            "pageSize": 100,
        },
    ),
    # ---- 全市场热门股吧（动态：自动抓取人气榜Top20个股股吧最新帖）----
    NewsSource(
        name="热门股吧",
        url="https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
        parser_type="em_dynamic_guba",
        method="POST",
        headers={
            "User-Agent": _PC_UA,
            "Referer": "https://gubatop.eastmoney.com/",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        params={
            "appId": "appId01",
            "globalId": "786e4c21-70dc-435a-93bb-38",
            "marketType": "",
            "pageNo": 1,
            "pageSize": 100,
        },
    ),
    # ---- 股吧首页热帖（跨板块）----
    NewsSource(
        name="东财股吧热帖",
        url="https://m.guba.eastmoney.com/",
        parser_type="em_mobile_guba",
        headers=_mobile_headers(),
    ),
    # ---- 综合UGC讨论平台 ----
    NewsSource(
        name="同花顺论股堂",
        url="https://t.10jqka.com.cn/",
        parser_type="ths_lounge",
        headers=_pc_headers("https://t.10jqka.com.cn/"),
    ),
    NewsSource(
        name="微博财经热搜",
        url="https://weibo.com/ajax/side/hotSearch",
        parser_type="weibo_finance",
        headers={
            "User-Agent": _PC_UA,
            "Referer": "https://weibo.com/",
            "Accept": "application/json",
        },
    ),
    NewsSource(
        name="新浪股吧",
        url="https://guba.sina.com.cn/",
        parser_type="sina_stock_bar",
        headers={
            "User-Agent": _PC_UA,
            "Referer": "https://guba.sina.com.cn/",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    ),
]

# ============================================================
# 同花顺原创栏目配置
# ============================================================
THSYC_CHANNELS = [
    {"name": "原创滚动盘评", "path": "ycall_list"},
    {"name": "盘后点睛",     "path": "djpingpan_list"},
    {"name": "快评",         "path": "djkuaiping_list"},
    {"name": "资金评盘",     "path": "zjpingpan_list"},
    {"name": "公告解读",     "path": "djggjd_list"},
    {"name": "公司互动",     "path": "djgshd_list"},
    {"name": "数据解读",     "path": "djsjdp_list"},
    {"name": "涨停解密",     "path": "mrnxgg_list"},
    {"name": "深度分析",     "path": "djsdfx_list"},
]
THSYC_BASE_URL = "http://yuanchuang.10jqka.com.cn"


def get_source_by_name(name: str) -> Optional[NewsSource]:
    """根据名称获取新闻源"""
    for src in FINANCE_NEWS_SOURCES:
        if src.name == name:
            return src
    return None


def get_enabled_sources() -> list[NewsSource]:
    """获取所有启用的新闻源（包含舆情论坛源）"""
    return [s for s in FINANCE_NEWS_SOURCES + FORUM_SOURCES if s.enabled]


def get_forum_sources() -> list[NewsSource]:
    """获取所有舆情论坛数据源"""
    return [s for s in FORUM_SOURCES if s.enabled]
