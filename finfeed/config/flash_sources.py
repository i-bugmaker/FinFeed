#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快讯模块

承载 7×24 小时实时快讯类新闻源（电报 / 简讯 / 直播流 / 推送快讯）。
这些源产出短消息，适合实时事件捕获与跨源语义去重。
原始 FINANCE_NEWS_SOURCES 已拆分至本模块与 article_sources 模块。"""

from finfeed.config.sources import NewsSource

FLASH_NEWS_SOURCES: list[NewsSource] = [
    NewsSource(
        name='财联社',
        url='https://www.cls.cn/api/cache?app=CailianpressWeb&name=telegraph&os=web&sv=8.7.9',
        parser_type='cls',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://www.cls.cn/telegraph',
            'Accept': 'application/json, text/plain, */*'
        },
    ),

    NewsSource(
        name='同花顺',
        url='https://news.10jqka.com.cn/tapp/news/push/stock',
        parser_type='ths',
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'http://news.10jqka.com.cn/',
            'Accept': 'application/json'
        },
        params={
            'page': 1,
            'tag': '',
            'type': 'all'
        },
    ),

    NewsSource(
        name='东方财富',
        url='https://np-listapi.eastmoney.com/comm/web/getFastNewsList',
        parser_type='eastmoney',
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://kuaixun.eastmoney.com/',
            'Accept': 'application/json'
        },
        params={
            'client': 'web',
            'biz': 'web_724',
            'fastColumn': '102',
            'sortEnd': '',
            'pageSize': 20
        },
    ),

    NewsSource(
        name='雅虎财经',
        url='https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,AAPL,MSFT&region=US&lang=en-US',
        parser_type='rss',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        },
    ),

    NewsSource(
        name='21经济网',
        url='https://api.21jingji.com/timestream/getListweb?page=1',
        parser_type='jingji21',
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.21jingji.com/',
            'Accept': 'application/json'
        },
    ),

    NewsSource(
        name='金十数据',
        url='https://www.jin10.com/flash_newest.js',
        parser_type='jin10',
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.jin10.com/',
            'Accept': '*/*'
        },
    ),

    NewsSource(
        name='格隆汇快讯',
        url='https://www.gelonghui.com/api/live-channels/all/lives/v4',
        parser_type='gelonghui_live',
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.gelonghui.com/live',
            'Accept': 'application/json'
        },
        params={
            'category': 'all',
            'limit': 15
        },
    ),

    NewsSource(
        name='法布财经',
        url='https://api.fastbull.cn/fastbull-news-service/api/getNewsPageByTagIds',
        parser_type='fastbull',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://www.fastbull.cn/',
            'Accept': 'application/json',
            'Origin': 'https://www.fastbull.cn'
        },
        params={
            'pageNo': 1,
            'pageSize': 30
        },
    ),

    NewsSource(
        name='企查查',
        url='https://www.qcc.com/api/home/getNewsFlash?firstRankIndex=1&lastRankIndex=0&lastRankTime=&pageSize=30',
        parser_type='qcc',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.qcc.com/',
            'Accept': 'application/json'
        },
    ),

    NewsSource(
        name='每经网',
        url='https://live.nbd.com.cn/',
        parser_type='nbd',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://live.nbd.com.cn/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='第一财经',
        url='https://www.yicai.com/api/ajax/getbrieflist',
        parser_type='yicai',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.yicai.com/brief/',
            'Accept': 'application/json'
        },
        params={
            'page': 1,
            'pagesize': 20,
            'id': 0
        },
    ),

    NewsSource(
        name='中证快讯',
        url='https://www.cs.com.cn/sylm/jsbd/list.html',
        parser_type='zhongzheng',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.cs.com.cn/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='上海证券报',
        url='https://www.cnstock.com/fastNews/10004',
        parser_type='cnstock',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.cnstock.com/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='爱股票',
        url='https://apis.aigupiao.com/Express/express_list/',
        parser_type='aigupiao',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://news.aigupiao.com/',
            'Accept': 'application/json, text/plain, */*'
        },
        params={
            'source': 'pc',
            'web_data': 'yes',
            'number': 20,
            'before': 0
        },
    ),

    NewsSource(
        name='新华财经',
        url='https://www.cnfin.com/news/index.html',
        parser_type='xinhuacaijing',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://www.cnfin.com/',
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'zh-CN,zh;q=0.9'
        },
    ),

    NewsSource(
        name='金融界',
        url='https://gateway.jrj.com/jrj-news/news/queryNewsFlash',
        parser_type='jrj',
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'productId': '6000021',
            'Referer': 'https://24h.jrj.com.cn/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*'
        },
        params={
            'makeDate': ''
        },
    ),

    NewsSource(
        name='财新网',
        url='https://gateway.caixin.com/api/dataplatform/scroll/index',
        parser_type='caixin',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://www.caixin.com/',
            'Accept': 'application/json, text/plain, */*'
        },
        params={
            'page': 1,
            'size': 50,
            'date': '',
            'channel': ''
        },
    ),

    NewsSource(
        name='汇通网快讯',
        url='https://www.fx678.com/kx/ajax/zykx',
        parser_type='fx678',
        method='POST',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://www.fx678.com/kx/',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest'
        },
    ),

    NewsSource(
        name='新浪财经7×24',
        url='https://zhibo.sina.com.cn/api/zhibo/feed',
        parser_type='sina724',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://zhibo.sina.com.cn/finance/152',
            'Accept': 'application/json, text/plain, */*'
        },
        params={
            'page_size': 100,
            'zhibo_id': 152,
            'tag_id': 0,
            'dire': 'f',
            'dpc': 1
        },
    ),

    NewsSource(
        name='富途牛牛快讯',
        url='https://news.futunn.com/news-site-api/main/get-flash-list',
        parser_type='futu',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://news.futunn.com/main/live',
            'Accept': 'application/json, text/plain, */*'
        },
        params={
            'pageSize': 20
        },
    ),

NewsSource(
        name='英为财情',
        url='https://cn.investing.com/news/latest-news',
        parser_type='investing_cn',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*'
        },
    ),
]


def get_flash_sources() -> list[NewsSource]:
    """返回本模块全部新闻源"""
    return FLASH_NEWS_SOURCES
