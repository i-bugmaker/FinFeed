#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用工具函数"""

import random


def jitter_interval(base: int, jitter_ratio: float = 0.3) -> float:
    """带抖动的等待间隔：基础间隔 ± jitter_ratio 随机浮动

    用于避免固定节奏被封 IP
    """
    lo = base * (1 - jitter_ratio)
    hi = base * (1 + jitter_ratio)
    return random.uniform(lo, hi)
