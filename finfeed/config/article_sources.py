#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财经文章模块

承载文章类新闻源（栏目图文、深度报道、研报）及巨潮公告。
与快讯模块（flash_sources）相互独立。
原始 FINANCE_NEWS_SOURCES 已拆分至本模块与 flash_sources 模块。"""

from finfeed.config.sources import NewsSource

ARTICLE_NEWS_SOURCES: list[NewsSource] = [
    NewsSource(
        name='新浪财经',
        url='https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num=15',
        parser_type='sina',
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/',
            'Accept': 'application/json'
        },
    ),

    NewsSource(
        name='同花顺原创',
        url='https://yuanchuang.10jqka.com.cn',
        parser_type='ths_yc',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://yuanchuang.10jqka.com.cn/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='同花顺财经',
        url='https://news.10jqka.com.cn/today_list/',
        parser_type='ths_finance',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://news.10jqka.com.cn/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='华尔街见闻',
        url='https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&accept=article&limit=30',
        parser_type='wallstreetcn',
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://wallstreetcn.com/',
            'Accept': 'application/json'
        },
    ),

    NewsSource(
        name='格隆汇文章',
        url='https://www.gelonghui.com/news/',
        parser_type='gelonghui_article',
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://www.gelonghui.com/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='巨潮公告',
        url='https://www.cninfo.com.cn/new/hisAnnouncement/query',
        parser_type='cninfo',
        method='POST',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice',
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Origin': 'https://www.cninfo.com.cn',
            'X-Requested-With': 'XMLHttpRequest'
        },
        params={
            'pageNum': '1',
            'pageSize': '30',
            'column': '',
            'tabName': 'fulltext',
            'plate': '',
            'stock': '',
            'searchkey': '',
            'secid': '',
            'category': '',
            'trade': '',
            'seDate': '',
            'sortName': '',
            'sortType': '',
            'isHLtitle': 'true'
        },
    ),

    NewsSource(
        name='cnBeta',
        url='https://rss.cnbeta.com.tw/',
        parser_type='rss',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        },
        verify_ssl=False,
    ),

    NewsSource(
        name='凤凰财经',
        url='https://finance.ifeng.com/',
        parser_type='ifeng',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://finance.ifeng.com/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='界面新闻',
        url='https://www.jiemian.com/',
        parser_type='jiemian',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.jiemian.com/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='澎湃新闻',
        url='https://www.thepaper.cn/',
        parser_type='thepaper',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.thepaper.cn/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='和讯网',
        url='https://stock.hexun.com/',
        parser_type='hexun',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://stock.hexun.com/',
            'Accept': 'text/html'
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
        name='韭研公社',
        url='https://www.jiuyangongshe.com',
        parser_type='jiuyan',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.jiuyangongshe.com/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='萝卜投研',
        url='https://robo.datayes.com/',
        parser_type='luobo',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://robo.datayes.com/',
            'Accept': 'text/html'
        },
    ),

    NewsSource(
        name='东方财富研报',
        url='https://reportapi.eastmoney.com/report/list',
        parser_type='em_research',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Referer': 'https://data.eastmoney.com/report/',
            'Accept': 'application/json, text/plain, */*'
        },
    ),

    NewsSource(
        name='港交所披露易',
        url='https://www1.hkexnews.hk/search/titleSearchServlet.do',
        parser_type='hkexnews',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*'
        },
    ),

    NewsSource(
        name='SEC EDGAR',
        url='https://www.sec.gov/cgi-bin/browse-edgar',
        parser_type='sec_edgar',
        headers={
            'User-Agent': 'FinFeed research contact@finfeed.example.com',
            'Accept': 'application/atom+xml, application/xml, text/xml, */*'
        },
        params={
            'type': '8-K'
        },
    ),

    NewsSource(
        name='上交所公告',
        url='http://query.sse.com.cn/security/stock/queryCompanyBulletinNew.do',
        parser_type='sse',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Referer': 'http://www.sse.com.cn/disclosure/listedinfo/announcement/',
            'Accept': 'application/json, text/plain, */*'
        },
    ),

    NewsSource(
        name='深交所公告',
        url='http://www.szse.cn/api/disc/announcement/annList',
        parser_type='szse',
        method='POST',
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Referer': 'http://www.szse.cn/disclosure/listed/notice/index.html',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json'
        },
        params={
            'channelCode': ['listedNotice_disc'],
            'seDate': [],
            'pageSize': 50,
            'pageNum': 1,
        },
    ),
]


def get_article_sources() -> list[NewsSource]:
    """返回本模块全部新闻源"""
    return ARTICLE_NEWS_SOURCES
