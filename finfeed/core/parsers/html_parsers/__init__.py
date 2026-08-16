#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML 页面类新闻源解析器包"""

import logging

from ._shared import _extract_time_from_parent, _find_link_near_time
from .cnstock import CNStockParser
from .fastbull import FastbullParser
from .gelonghui import GelonghuiArticleParser
from .hexun import HexunParser
from .ifeng import IfengParser
from .investing_cn import InvestingCnParser
from .jiemian import JiemianParser
from .jiuyan import JiuyanParser
from .luobo import LuoBoParser
from .nbd import NBDParser
from .sec_edgar import SecEdgarParser
from .thepaper import ThePaperParser
from .xinhua import XinhuaCaijingParser
from .yicai import YicaiParser
from .zhongzheng import ZhongzhengParser

logger = logging.getLogger("news_monitor")

__all__ = [
    "_extract_time_from_parent",
    "_find_link_near_time",
    "GelonghuiArticleParser",
    "FastbullParser",
    "NBDParser",
    "HexunParser",
    "IfengParser",
    "JiemianParser",
    "ThePaperParser",
    "YicaiParser",
    "LuoBoParser",
    "ZhongzhengParser",
    "JiuyanParser",
    "CNStockParser",
    "XinhuaCaijingParser",
    "InvestingCnParser",
    "SecEdgarParser",
]
