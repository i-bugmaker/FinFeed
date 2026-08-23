#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金融文本情感分析模块（词典法改进版）

改进点：
- 否定词检测（不、没、无、未、别、莫、勿、毋、非、否）
- 程度副词加权（非常、极其、特别、大幅、显著...）
- 转折词处理（但是、然而、却... 后面内容权重更高）
- 词典覆盖更全面的金融术语
"""

import asyncio
import re
from typing import List

from finfeed.storage.models import NewsItem

POSITIVE_WORDS = {
    "利好": 3, "大涨": 4, "涨停": 5, "牛市": 4, "上涨": 2, "增长": 2, "盈利": 2,
    "利润": 1, "突破": 2, "新高": 3, "反弹": 2, "回暖": 2, "复苏": 2, "超预期": 4,
    "业绩": 1, "增持": 3, "回购": 3, "分红": 2, "中标": 3, "签约": 2, "合作": 1,
    "获批": 3, "通过": 1, "创新高": 4, "翻倍": 5, "暴涨": 5, "拉升": 3, "走强": 2,
    "领涨": 3, "飘红": 2, "看多": 2, "看涨": 2, "看好": 2, "乐观": 2, "景气": 2,
    "高增长": 3, "超预期": 4, "大超预期": 5, "净利润增": 3, "同比增": 2, "环比增": 2,
    "营收增": 2, "毛利提升": 2, "净利率提升": 2, "订单增长": 2, "产能扩张": 2,
    "行业龙头": 2, "市占率提升": 2, "政策支持": 2, "补贴": 2, "降准": 2, "降息": 2,
    "流动性宽松": 2, "资金流入": 2, "外资加仓": 2, "机构买入": 2, "北向买入": 2,
    "技术突破": 3, "新品发布": 2, "产能释放": 2, "业绩预增": 4, "扭亏": 3,
    "摘帽": 3, "重组成功": 4, "并购": 2, "战略投资": 2, "签大单": 3, "入摩": 3,
    "入富": 3, "纳入指数": 2, "评级上调": 2, "目标价上调": 2, "买入评级": 2,
    "推荐": 2, "强烈推荐": 3, "增持评级": 2, "跑赢行业": 2, "金叉": 2, "放量上涨": 3,
}

NEGATIVE_WORDS = {
    "利空": 3, "大跌": 4, "跌停": 5, "熊市": 4, "下跌": 2, "亏损": 3, "下滑": 2,
    "下降": 2, "新低": 3, "暴跌": 5, "跳水": 4, "崩盘": 5, "破位": 2, "走弱": 2,
    "领跌": 3, "飘绿": 2, "看空": 2, "看跌": 2, "悲观": 2, "低迷": 2, "不景气": 2,
    "不及预期": 4, "低于预期": 3, "业绩暴雷": 5, "亏损扩大": 3, "净利润降": 3,
    "同比降": 2, "环比降": 2, "营收降": 2, "毛利下滑": 2, "订单减少": 2, "产能过剩": 2,
    "处罚": 3, "违规": 3, "立案调查": 4, "ST": 4, "*ST": 5, "退市": 5, "摘牌": 5,
    "减持": 3, "套现": 2, "质押": 1, "爆仓": 5, "债务违约": 5, "逾期": 3, "破产": 5,
    "清算": 4, "重组失败": 4, "中标失败": 2, "项目终止": 2, "合作终止": 2,
    "被否": 3, "未通过": 3, "暂停": 2, "叫停": 3, "禁令": 3, "制裁": 4,
    "贸易战": 4, "加征关税": 3, "反倾销": 3, "反垄断": 2, "罚款": 2, "警示函": 2,
    "监管函": 2, "问询函": 1, "关注函": 1, "评级下调": 3, "目标价下调": 2,
    "卖出评级": 2, "减持评级": 2, "跑输行业": 2, "死叉": 2, "放量下跌": 3,
    "资金流出": 2, "外资减仓": 2, "机构卖出": 2, "北向卖出": 2, "解禁": 2,
    "大小非": 2, "大股东减持": 3, "高管减持": 2, "造假": 5, "欺诈": 5, "虚增": 4,
    "财务造假": 5, "商誉减值": 3, "资产减值": 3, "计提": 2, "预亏": 4, "预减": 3,
    "黑天鹅": 5, "灰犀牛": 4, "踩踏": 3, "恐慌": 3, "抛售": 3, "割肉": 2,
}

NEGATION_WORDS = {
    "不", "没", "无", "未", "别", "莫", "勿", "毋", "非", "否", "没", "没有",
    "不是", "不会", "不能", "不大", "不再", "不够", "不足", "未必", "并非",
    "毫无", "绝不", "永不", "从不", "从未",
}

INTENSIFIERS = {
    "非常": 1.5, "极其": 2.0, "特别": 1.5, "大幅": 1.5, "显著": 1.5, "明显": 1.3,
    "持续": 1.2, "快速": 1.3, "稳步": 1.2, "剧烈": 1.8, "大幅": 1.5, "超": 1.5,
    "极度": 2.0, "异常": 1.5, "相当": 1.3, "较为": 1.1, "略微": 0.8, "稍微": 0.8,
    "远超": 2.0, "远不及": 2.0, "大大": 1.5, "进一步": 1.2, "继续": 1.1,
}

TRANSITION_WORDS = {"但是", "但", "然而", "却", "可是", "不过", "反之", "相反", "而"}


def _split_sentences(text: str) -> List[str]:
    """将文本按标点分割成短句"""
    sentences = re.split(r'[。！？；\n\r]+', text)
    return [s.strip() for s in sentences if s.strip()]


def _analyze_clause(text: str) -> float:
    """分析单个子句的情感得分，考虑否定词和程度副词"""
    if not text:
        return 0.0

    score = 0.0
    words = list(text)
    n = len(words)

    for word, weight in {**POSITIVE_WORDS, **NEGATIVE_WORDS}.items():
        wl = len(word)
        idx = 0
        while True:
            pos = text.find(word, idx)
            if pos < 0:
                break

            w = weight
            if word in NEGATIVE_WORDS:
                w = -w

            window_start = max(0, pos - 6)
            window = text[window_start:pos]

            has_negation = False
            for neg in NEGATION_WORDS:
                if neg in window:
                    has_negation = True
                    break
            if has_negation:
                w = -w * 0.8

            for intensifier, factor in INTENSIFIERS.items():
                if intensifier in window:
                    w *= factor
                    break

            score += w
            idx = pos + wl

    return score


def analyze_sentiment(text: str, title: str = "") -> tuple[str, float]:
    """分析文本情感极性

    Args:
        text: 正文/摘要
        title: 标题（权重更高）

    Returns:
        (情感: positive/negative/neutral, 置信度 0-1)
    """
    full_text = f"{title} {title} {text}" if title else text
    if not full_text:
        return "neutral", 0.0

    sentences = _split_sentences(full_text)
    total_score = 0.0

    for sent in sentences:
        clauses = re.split(r'(但是|但|然而|却|可是|不过)', sent)
        weight = 1.0
        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue
            if clause in TRANSITION_WORDS:
                weight = 1.5
                continue
            total_score += _analyze_clause(clause) * weight
            weight = 1.0

    if title:
        title_score = _analyze_clause(title) * 2.0
        total_score += title_score

    threshold = 1.5
    if total_score > threshold:
        confidence = min(abs(total_score) / 15.0, 1.0)
        return "positive", max(confidence, 0.5)
    elif total_score < -threshold:
        confidence = min(abs(total_score) / 15.0, 1.0)
        return "negative", max(confidence, 0.5)
    else:
        confidence = 1.0 - min(abs(total_score) / threshold, 1.0) * 0.5
        return "neutral", max(confidence, 0.5)


IMPORTANCE_KEYWORDS = {
    "央行": 5, "国务院": 5, "证监会": 5, "银保监会": 5, "发改委": 4,
    "财政部": 4, "工信部": 4, "政治局": 5, "中央经济工作会议": 5,
    "降息": 4, "降准": 4, "加息": 4, "LPR": 3, "MLF": 3, "逆回购": 2,
    "GDP": 3, "CPI": 3, "PPI": 3, "PMI": 3, "社融": 3, "M2": 2,
    "重磅": 4, "突发": 4, "紧急": 3, "官宣": 4, "刚刚": 3,
    "涨停": 3, "跌停": 3, "熔断": 5, "牛市": 4, "熊市": 4,
    "业绩预告": 2, "业绩快报": 2, "年报": 2, "季报": 2, "中报": 2,
    "重组": 3, "并购": 2, "借壳": 4, "IPO": 2, "退市": 4,
    "处罚": 3, "立案": 4, "调查": 2,
}


def score_importance(news: NewsItem) -> float:
    """评估新闻重要性

    Returns:
        重要性分数 0-10
    """
    score = 1.0
    text = f"{news.title} {news.intro}"

    for keyword, weight in IMPORTANCE_KEYWORDS.items():
        if keyword in text:
            score += weight

    if news.sentiment == "positive" or news.sentiment == "negative":
        score += 0.5

    if news.stocks and len(news.stocks) >= 2:
        score += 0.5
    if news.stocks and len(news.stocks) >= 5:
        score += 0.5

    return min(score, 10.0)


async def analyze_sentiment_async(news: NewsItem) -> str:
    """异步情感分析（在事件循环中执行）"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, analyze_sentiment, news.intro or "", news.title or ""
    )
    return result[0]


async def analyze_sentiment_with_confidence(news: NewsItem) -> tuple[str, float]:
    """异步情感分析（带置信度）"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, analyze_sentiment, news.intro or "", news.title or ""
    )
    return result
