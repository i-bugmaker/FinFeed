#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""情感分析模块

基于金融财经领域词典的轻量级情感分析，不依赖大型模型。
输出：positive（正面）、neutral（中性）、negative（负面）
"""

from typing import Tuple

# 正面情感词（财经领域）
_POSITIVE_WORDS = [
    "增长", "上涨", "上升", "提升", "增加", "扩大", "突破", "创新高",
    "盈利", "利润增长", "业绩增长", "营收增长", "超预期", "超市场预期",
    "利好", "增持", "买入", "推荐", "评级上调", "上调",
    "回暖", "复苏", "反弹", "走强", "走高", "冲高",
    "积极", "乐观", "强劲", "稳健", "良好", "优异",
    "签约", "落地", "投产", "量产", "获批", "通过",
    "合作", "战略投资", "收购", "重组", "借壳",
    "分红", "高送转", "回购", "增持计划",
    "暴涨", "大涨", "飙升", "激增", "暴增",
    "涨停", "连板", "晋级",
]

# 负面情感词（财经领域）
_NEGATIVE_WORDS = [
    "下跌", "下降", "减少", "萎缩", "下滑", "回落", "走低",
    "亏损", "利润下降", "业绩下滑", "营收下降", "不及预期",
    "利空", "减持", "卖出", "评级下调", "下调",
    "暴跌", "大跌", "重挫", "跳水", "崩盘", "爆雷",
    "风险", "危机", "衰退", "萧条", "疲软", "低迷",
    "违约", "逾期", "坏账", "亏损", "ST", "*ST",
    "调查", "立案", "处罚", "罚款", "警示",
    "退市", "停牌", "解禁", "减持计划",
    "跌停", "炸板", "破发",
    "质疑", "造假", "财务造假", "欺诈",
    "破产", "清算", "倒闭",
]

# 程度副词（加强/减弱情感强度）
_INTENSIFIERS_STRONG = ["大幅", "显著", "明显", "强劲", "剧烈", "暴", "大", "猛"]
_INTENSIFIERS_WEAK = ["小幅", "略有", "轻微", "小幅", "温和"]


def analyze_sentiment(title: str, intro: str = "") -> Tuple[str, float]:
    """分析新闻情感

    Args:
        title: 新闻标题
        intro: 新闻简介/正文

    Returns:
        (情感标签, 置信度)
        情感标签: positive / neutral / negative
        置信度: 0.0 - 1.0
    """
    text = f"{title} {intro or ''}"
    if not text.strip():
        return "neutral", 0.5

    pos_count = 0
    neg_count = 0

    # 统计正面词
    for word in _POSITIVE_WORDS:
        count = text.count(word)
        if count > 0:
            # 标题中的词权重更高
            title_weight = title.count(word) * 2
            intro_weight = count - title.count(word)
            pos_count += title_weight + intro_weight

    # 统计负面词
    for word in _NEGATIVE_WORDS:
        count = text.count(word)
        if count > 0:
            title_weight = title.count(word) * 2
            intro_weight = count - title.count(word)
            neg_count += title_weight + intro_weight

    # 考虑程度副词的加强作用
    def _apply_intensifiers(text: str, base_count: float, words: list[str]) -> float:
        result = base_count
        for w in words:
            idx = 0
            while True:
                idx = text.find(w, idx)
                if idx == -1:
                    break
                # 检查附近是否有情感词
                window = text[max(0, idx - 10):idx + 20]
                has_pos = any(pw in window for pw in _POSITIVE_WORDS[:30])
                has_neg = any(nw in window for nw in _NEGATIVE_WORDS[:30])
                if has_pos or has_neg:
                    result += 0.5
                idx += len(w)
        return result

    if pos_count > 0:
        pos_count = _apply_intensifiers(text, pos_count, _INTENSIFIERS_STRONG)
        pos_count = _apply_intensifiers(text, pos_count * 0.8, _INTENSIFIERS_WEAK)
    if neg_count > 0:
        neg_count = _apply_intensifiers(text, neg_count, _INTENSIFIERS_STRONG)
        neg_count = _apply_intensifiers(text, neg_count * 0.8, _INTENSIFIERS_WEAK)

    # 计算情感得分
    total = pos_count + neg_count
    if total == 0:
        return "neutral", 0.5

    pos_ratio = pos_count / total

    # 根据正面词比例判断情感
    if pos_ratio >= 0.65:
        sentiment = "positive"
        confidence = min(0.95, 0.5 + pos_ratio * 0.5)
    elif pos_ratio <= 0.35:
        sentiment = "negative"
        confidence = min(0.95, 0.5 + (1 - pos_ratio) * 0.5)
    else:
        sentiment = "neutral"
        confidence = 0.5 + abs(pos_ratio - 0.5)

    return sentiment, round(confidence, 2)


def get_sentiment_label(sentiment: str) -> str:
    """获取情感的中文标签"""
    labels = {
        "positive": "正面",
        "neutral": "中性",
        "negative": "负面",
    }
    return labels.get(sentiment, "中性")
