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


def truncate_text(text: str, max_len: int, suffix: str = "...") -> str:
    """截断文本到指定长度"""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - len(suffix)] + suffix
