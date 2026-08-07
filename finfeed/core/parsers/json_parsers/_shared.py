#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON 解析器包共享常量与辅助函数"""

import re
from datetime import timezone, timedelta

_RE_HHMM = re.compile(r"(\d{1,2}):(\d{2})")

_RE_MD_HHMM = re.compile(r"(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})")

TZ_BJ = timezone(timedelta(hours=8))
