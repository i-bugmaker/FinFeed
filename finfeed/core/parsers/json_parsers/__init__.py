#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON API 类新闻源解析器包"""

import logging

from ._shared import TZ_BJ, _RE_HHMM, _RE_MD_HHMM
from .sina import SinaParser
from .cls import CLSParser
from .aigupiao import AiGuPiaoParser
from .jrj import JrjParser
from .ths import THSParser
from .eastmoney import EastMoneyParser
from .jingji21 import Jingji21Parser
from .wallstreetcn import WallStreetCNParser
from .jin10 import Jin10Parser
from .gelonghui_live import GelonghuiLiveParser
from .qcc import QCCParser
from .cninfo import CninfoParser
from .thsyc import THSYCParser
from .thsfinance import THSFinanceParser

logger = logging.getLogger("news_monitor")

__all__ = [
    "TZ_BJ",
    "_RE_HHMM",
    "_RE_MD_HHMM",
    "SinaParser",
    "CLSParser",
    "AiGuPiaoParser",
    "JrjParser",
    "THSParser",
    "EastMoneyParser",
    "Jingji21Parser",
    "WallStreetCNParser",
    "Jin10Parser",
    "GelonghuiLiveParser",
    "QCCParser",
    "CninfoParser",
    "THSYCParser",
    "THSFinanceParser",
]
