#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析器工厂

根据新闻源的 parser_type 创建对应的 Parser 实例。
"""

from typing import Optional

from finfeed.config.sources import NewsSource
from .base import BaseParser
from .json_parsers import (
    SinaParser, CLSParser, THSParser, EastMoneyParser,
    Jingji21Parser, WallStreetCNParser, Jin10Parser,
    GelonghuiLiveParser, QCCParser, CninfoParser, THSYCParser,
)
from .html_parsers import GelonghuiArticleParser, FastbullParser, NBDParser, HexunParser, IfengParser, JiemianParser, ThePaperParser, YicaiParser, JiuyanParser
from .forum_parsers import (
    EastMoneyStockBarParser, EastMoneyHotBarParser,
    EastMoneyMobileGubaParser, EastMoneyHotRankParser, EastMoneyDynamicGubaParser,
    SinaStockBarParser, XueqiuHotParser,
    ThsAdvisorParser, ThsStockBarParser,
    ThsLoungeParser, WeiboFinanceParser,
)
from .rss_parsers import RSSParser

EastMoneyForumParser = EastMoneyStockBarParser

PARSER_MAP = {
    "sina": SinaParser,
    "cls": CLSParser,
    "ths": THSParser,
    "eastmoney": EastMoneyParser,
    "jingji21": Jingji21Parser,
    "wallstreetcn": WallStreetCNParser,
    "jin10": Jin10Parser,
    "gelonghui_live": GelonghuiLiveParser,
    "gelonghui_article": GelonghuiArticleParser,
    "qcc": QCCParser,
    "cninfo": CninfoParser,
    "ths_yc": THSYCParser,
    "fastbull": FastbullParser,
    "nbd": NBDParser,
    "hexun": HexunParser,
    "ifeng": IfengParser,
    "jiemian": JiemianParser,
    "thepaper": ThePaperParser,
    "yicai": YicaiParser,
    "jiuyan": JiuyanParser,
    "rss": RSSParser,
    "eastmoney_forum": EastMoneyStockBarParser,
    "eastmoney_hot": EastMoneyHotBarParser,
    "em_mobile_guba": EastMoneyMobileGubaParser,
    "em_hot_rank": EastMoneyHotRankParser,
    "em_dynamic_guba": EastMoneyDynamicGubaParser,
    "sina_stock_bar": SinaStockBarParser,
    "ths_advisor": ThsAdvisorParser,
    "ths_stock_bar": ThsStockBarParser,
    "xueqiu_hot": XueqiuHotParser,
    "ths_lounge": ThsLoungeParser,
    "weibo_finance": WeiboFinanceParser,
}


def create_parser(source: NewsSource) -> BaseParser:
    """根据新闻源创建对应的解析器

    Args:
        source: 新闻源配置

    Returns:
        对应的 Parser 实例，如果类型不匹配则默认使用 RSSParser
    """
    parser_cls = PARSER_MAP.get(source.parser_type, RSSParser)
    return parser_cls(source)


def register_parser(parser_type: str, parser_cls: type[BaseParser]):
    """注册新的解析器类型（用于扩展）"""
    PARSER_MAP[parser_type] = parser_cls
