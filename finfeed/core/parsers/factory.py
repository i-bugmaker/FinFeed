#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析器工厂

根据新闻源的 parser_type 创建对应的 Parser 实例。
支持装饰器注册和子类自动发现。
"""

import logging
from typing import Dict, Type, Optional

from finfeed.config.sources import NewsSource
from .base import BaseParser, get_registered_parsers
from .rss_parsers import RSSParser

logger = logging.getLogger(__name__)

_PARSER_MAP: Dict[str, Type[BaseParser]] = {}
_initialized = False


def _import_all_parsers() -> None:
    """导入所有解析器模块，触发类定义和注册"""
    global _initialized
    if _initialized:
        return
    
    from . import json_parsers, html_parsers, rss_parsers
    from . import forum_parsers
    
    _register_known_parsers()
    _initialized = True


def _register_known_parsers() -> None:
    """注册已知的解析器类型映射"""
    from .json_parsers import (
        SinaParser, CLSParser, THSParser, EastMoneyParser,
        Jingji21Parser, WallStreetCNParser, Jin10Parser,
        GelonghuiLiveParser, QCCParser, CninfoParser, THSYCParser,
        THSFinanceParser,
    )
    from .html_parsers import (
        GelonghuiArticleParser, FastbullParser, NBDParser,
        HexunParser, IfengParser, JiemianParser, ThePaperParser,
        YicaiParser, JiuyanParser, LuoBoParser, CNStockParser,
        ZhongzhengParser,
    )
    from .forum_parsers import (
        EastMoneyStockBarParser, EastMoneyHotBarParser,
        EastMoneyMobileGubaParser, EastMoneyHotRankParser,
        EastMoneyDynamicGubaParser, SinaStockBarParser,
        ThsAdvisorParser, ThsStockBarParser,
        ThsLoungeParser, WeiboFinanceParser,
    )
    
    _PARSER_MAP.update({
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
        "ths_finance": THSFinanceParser,
        "fastbull": FastbullParser,
        "nbd": NBDParser,
        "hexun": HexunParser,
        "ifeng": IfengParser,
        "jiemian": JiemianParser,
        "thepaper": ThePaperParser,
        "yicai": YicaiParser,
        "jiuyan": JiuyanParser,
        "luobo": LuoBoParser,
        "cnstock": CNStockParser,
        "zhongzheng": ZhongzhengParser,
        "rss": RSSParser,
        "eastmoney_forum": EastMoneyStockBarParser,
        "eastmoney_hot": EastMoneyHotBarParser,
        "em_mobile_guba": EastMoneyMobileGubaParser,
        "em_hot_rank": EastMoneyHotRankParser,
        "em_dynamic_guba": EastMoneyDynamicGubaParser,
        "sina_stock_bar": SinaStockBarParser,
        "ths_advisor": ThsAdvisorParser,
        "ths_stock_bar": ThsStockBarParser,
        "ths_lounge": ThsLoungeParser,
        "weibo_finance": WeiboFinanceParser,
    })
    
    for parser_type, parser_cls in get_registered_parsers().items():
        if parser_type not in _PARSER_MAP:
            _PARSER_MAP[parser_type] = parser_cls


def create_parser(source: NewsSource) -> BaseParser:
    """根据新闻源创建对应的解析器

    Args:
        source: 新闻源配置

    Returns:
        对应的 Parser 实例，如果类型不匹配则默认使用 RSSParser
    """
    if not _initialized:
        _import_all_parsers()
    
    parser_cls = _PARSER_MAP.get(source.parser_type, RSSParser)
    return parser_cls(source)


def register_parser(parser_type: str, parser_cls: Type[BaseParser]) -> None:
    """注册新的解析器类型（用于扩展）"""
    _PARSER_MAP[parser_type] = parser_cls


def get_all_parser_types() -> Dict[str, Type[BaseParser]]:
    """获取所有已注册的解析器类型"""
    if not _initialized:
        _import_all_parsers()
    return dict(_PARSER_MAP)
