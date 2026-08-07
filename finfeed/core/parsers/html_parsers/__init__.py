#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML 页面类新闻源解析器包"""

import logging

from ._shared import _extract_time_from_parent, _find_link_near_time
from .gelonghui import GelonghuiArticleParser
from .fastbull import FastbullParser
from .nbd import NBDParser
from .hexun import HexunParser
from .ifeng import IfengParser
from .jiemian import JiemianParser
from .thepaper import ThePaperParser
from .yicai import YicaiParser
from .luobo import LuoBoParser
from .zhongzheng import ZhongzhengParser
from .jiuyan import JiuyanParser
from .cnstock import CNStockParser
from .xinhua import XinhuaCaijingParser

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
]
