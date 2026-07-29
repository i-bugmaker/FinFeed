#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""哈希与去重相关工具函数"""

import re
import hashlib
import unicodedata


def normalize_title(title: str) -> str:
    """标题标准化：去除标点、来源前缀、多余空白，统一字符，用于L2精确哈希去重"""
    if not title:
        return ""
    t = title.strip()
    # 全角转半角
    t = unicodedata.normalize("NFKC", t)
    # 去除已知来源前缀（更精确的匹配，避免误删标题主体）
    known_source_prefixes = [
        "财联社", "新浪财经", "新浪财经讯", "东方财富", "东财", "同花顺",
        "金十数据", "华尔街见闻", "格隆汇", "新华财经", "中证快讯", "第一财经",
        "21世纪经济报道", "21经济网", "界面新闻", "澎湃新闻", "凤凰财经",
        "每经网", "每经", "和讯网", "上海证券报", "上证报", "中证网",
        "网易财经", "腾讯财经", "搜狐财经",
    ]
    for source in known_source_prefixes:
        patterns = [
            rf"^{re.escape(source)}\s*[|：:]\s*",
            rf"^{re.escape(source)}讯\s*[|：:]?\s*",
        ]
        for pat in patterns:
            t = re.sub(pat, "", t, count=1)
    # 去除 【xxx】 格式前缀（如【重磅】【公告】等）
    t = re.sub(r"^【[^】]{1,10}】\s*", "", t)
    t = re.sub(r"^\[[^\]]{1,10}\]\s*", "", t)
    # 去除 | 分隔的来源后缀
    t = re.sub(r"\s*\|[^|]{0,15}$", "", t)
    # 去除URL
    t = re.sub(r"https?://\S+", "", t)
    # 去除数字中的小数点和逗号（如 "0.5个百分点" -> "05个百分点"，"1,000亿" -> "1000亿"）
    t = re.sub(r"(\d)[.,](\d)", r"\1\2", t)
    # 去除所有标点符号（中英文）
    t = re.sub(r"[^\w\u4e00-\u9fff]", "", t)
    # 去除所有空白
    t = re.sub(r"\s+", "", t)
    return t.lower()


def compute_title_full_hash(title: str) -> str:
    """计算标题的完整 MD5 哈希（用于精确去重）"""
    return hashlib.md5(title.encode("utf-8")).hexdigest()


def compute_normalized_title_hash(title: str) -> str:
    """计算标准化标题的 MD5 哈希（用于L2跨源精确去重）"""
    normalized = normalize_title(title)
    if not normalized:
        return ""
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def compute_url_hash(url: str) -> str:
    """计算 URL 的 MD5 哈希（用于精确去重）"""
    if not url or url == "#":
        return ""
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def compute_simhash(text: str) -> int:
    """计算文本的 SimHash 值（64位整型，用于语义去重）

    基于关键词 + 哈希的简化版 SimHash 算法：
    1. 将文本分词（这里用字符 n-gram 替代，避免依赖分词库）
    2. 每个特征计算 64 位哈希
    3. 按位加权求和，正数位为1，负数位为0
    """
    if not text:
        return 0

    text = text.strip().lower()
    if len(text) < 2:
        return 0

    features = []
    for i in range(len(text) - 1):
        features.append(text[i:i+2])
    if len(text) >= 3:
        for i in range(len(text) - 2):
            features.append(text[i:i+3])

    weights = {}
    for f in features:
        weights[f] = weights.get(f, 0) + 1

    bits = [0] * 64
    for feat, weight in weights.items():
        h = hashlib.md5(feat.encode("utf-8")).digest()
        h_int = int.from_bytes(h[:8], "big")
        for i in range(64):
            if h_int & (1 << (63 - i)):
                bits[i] += weight
            else:
                bits[i] -= weight

    simhash = 0
    for i in range(64):
        if bits[i] > 0:
            simhash |= (1 << (63 - i))

    return simhash


def simhash_to_hex(simhash: int) -> str:
    """将 SimHash 整数转为十六进制字符串（用于数据库存储）"""
    return format(simhash & 0xFFFFFFFFFFFFFFFF, "016x")


def hex_to_simhash(hex_str: str) -> int:
    """将十六进制字符串转为 SimHash 整数"""
    if not hex_str:
        return 0
    try:
        return int(hex_str, 16)
    except (ValueError, TypeError):
        return 0


def hamming_distance(h1: int, h2: int) -> int:
    """计算两个 64 位整数的汉明距离"""
    x = h1 ^ h2
    dist = 0
    while x:
        dist += 1
        x &= x - 1
    return dist


def is_semantic_duplicate(hash1: int, hash2: int, threshold: int = 3) -> bool:
    """判断两个 SimHash 是否语义重复（汉明距离 <= threshold）"""
    return hamming_distance(hash1, hash2) <= threshold
