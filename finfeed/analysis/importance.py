#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻重要性评分

基于多维度的新闻重要性评估：
1. 来源权重（权威媒体权重更高）
2. 关键词权重（重要关键词加分）
3. 涉及股票数量
4. 标题长度与信息量
5. 事件类型权重（重大事件加分）
"""

from typing import Optional

# 来源权重配置
_SOURCE_WEIGHTS = {
    "财联社": 1.3,
    "华尔街见闻": 1.2,
    "金十数据": 1.2,
    "新浪财经": 1.1,
    "东方财富": 1.1,
    "同花顺": 1.1,
    "格隆汇": 1.0,
    "雪球": 0.9,
    "21经济网": 1.0,
    "雅虎财经": 0.8,
    "法布财经": 0.9,
    "企查查": 0.8,
    "同花顺原创": 0.9,
    "巨潮公告": 1.1,
    "cnBeta": 0.7,
}

# 高权重关键词（重要事件）
_HIGH_IMPACT_KEYWORDS = [
    "央行", "降准", "降息", "加息", "政治局", "国务院", "证监会",
    "IPO", "注册制", "退市新规", "印花税",
    "暴涨", "暴跌", "熔断", "千股涨停", "千股跌停",
    "重大重组", "借壳", "要约收购",
    "宁德时代", "茅台", "贵州茅台", "腾讯", "阿里", "比亚迪",
    "GPT", "ChatGPT", "AI大模型", "英伟达",
    "新冠", "疫情", "地缘政治", "战争", "制裁",
    "美联储", "加息", "降息",
]

# 中等权重关键词
_MEDIUM_IMPACT_KEYWORDS = [
    "业绩预告", "业绩快报", "年报", "半年报", "季报",
    "回购", "增持", "减持", "分红", "送转",
    "中标", "签约", "战略合作",
    "涨价", "降价",
    "获批", "通过", "核准",
    "调研", "机构调研",
    "龙虎榜", "北向资金", "南向资金",
]

# 低权重关键词
_LOW_IMPACT_KEYWORDS = [
    "公司问答", "投资者互动", "投资者关系",
    "公告", "披露",
    "股价", "涨跌",
]


def compute_importance(title: str, intro: str = "", source: str = "",
                        stocks_count: int = 0) -> float:
    """计算新闻重要性评分（0-10分）

    Args:
        title: 新闻标题
        intro: 新闻简介
        source: 来源名称
        stocks_count: 涉及股票数量

    Returns:
        重要性评分（0-10）
    """
    score = 5.0  # 基础分

    # 1. 来源权重
    source_weight = _SOURCE_WEIGHTS.get(source, 1.0)
    score += (source_weight - 1.0) * 3

    # 2. 关键词权重
    text = f"{title} {intro}"
    high_count = sum(1 for kw in _HIGH_IMPACT_KEYWORDS if kw in text)
    medium_count = sum(1 for kw in _MEDIUM_IMPACT_KEYWORDS if kw in text)
    low_count = sum(1 for kw in _LOW_IMPACT_KEYWORDS if kw in text)

    # 标题中的关键词权重更高
    title_high = sum(1 for kw in _HIGH_IMPACT_KEYWORDS if kw in title)
    title_medium = sum(1 for kw in _MEDIUM_IMPACT_KEYWORDS if kw in title)

    score += high_count * 1.5 + title_high * 0.5
    score += medium_count * 0.8 + title_medium * 0.3
    score += low_count * 0.3

    # 3. 涉及股票数量
    if stocks_count > 0:
        score += min(stocks_count, 5) * 0.3

    # 4. 标题信息量（长度适中的标题可能更重要）
    title_len = len(title)
    if 15 <= title_len <= 40:
        score += 0.3
    elif title_len > 40:
        score += 0.5

    # 5. 是否包含数字（数据新闻通常更重要）
    import re
    if re.search(r'\d+(\.\d+)?%', text) or re.search(r'[增减].{0,3}\d+', text):
        score += 0.3

    # 6. 分类加权
    if "宏观" in source or "政策" in text or "央行" in text:
        score += 0.5

    # 限制在 0-10 分
    score = max(0.0, min(10.0, score))
    return round(score, 1)


def get_importance_level(score: float) -> str:
    """获取重要性等级标签"""
    if score >= 8.0:
        return "极重要"
    elif score >= 6.5:
        return "重要"
    elif score >= 5.0:
        return "一般"
    elif score >= 3.0:
        return "较低"
    else:
        return "低"
