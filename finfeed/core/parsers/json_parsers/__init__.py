#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON API 类新闻源解析器包"""

import logging

from ._shared import _RE_HHMM, _RE_MD_HHMM, TZ_BJ
from .aigupiao import AiGuPiaoParser
from .caixin import CaixinParser
from .cls import CLSParser
from .cninfo import CninfoParser
from .eastmoney import EastMoneyParser
from .em_research import EmResearchParser
from .futu import FutuParser
from .fx678 import Fx678Parser
from .gelonghui_live import GelonghuiLiveParser
from .hkexnews import HkexNewsParser
from .jin10 import Jin10Parser
from .jingji21 import Jingji21Parser
from .jrj import JrjParser
from .qcc import QCCParser
from .sina import SinaParser
from .sina724 import Sina724Parser
from .sse import SseParser
from .szse import SzseParser
from .ths import THSParser
from .thsfinance import THSFinanceParser
from .thsyc import THSYCParser
from .wallstreetcn import WallStreetCNParser

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
    "CaixinParser",
    "Fx678Parser",
    "Sina724Parser",
    "FutuParser",
    "EmResearchParser",
    "HkexNewsParser",
    "SseParser",
    "SzseParser",
]
