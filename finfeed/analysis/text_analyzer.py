#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文本分析与信息提取模块

功能：
- 股票代码识别（A股主板/科创板/创业板）
- 关键词提取（TF-IDF 简化版）
- 后续扩展：情感分析、实体识别、事件抽取等
"""

import re
from collections import Counter
from typing import Optional


# ============================================================
# 股票代码识别
# ============================================================

# A股代码规则：
# 沪市主板：600, 601, 603, 605 开头，6位
# 沪市科创板：688 开头，6位
# 深市主板：000, 001, 002, 003 开头，6位
# 深市创业板：300, 301 开头，6位
# 北交所：43, 83, 87, 88 等开头（暂不纳入）

STOCK_PATTERNS = [
    # 带 .SH / .SZ 后缀的，如 600519.SH
    (re.compile(r'\b(60[0-9]{4}|688[0-9]{3})\.(SH|sh)\b'), 'sh'),
    (re.compile(r'\b(00[0-9]{4}|30[0-9]{4})\.(SZ|sz)\b'), 'sz'),
    # 括号标注的，如 贵州茅台(600519)
    (re.compile(r'[(（](60[0-9]{4}|688[0-9]{3})[)）]'), 'sh'),
    (re.compile(r'[(（](00[0-9]{4}|30[0-9]{4})[)）]'), 'sz'),
    # 中文 + 代码 格式，如 茅台600519
    (re.compile(r'[\u4e00-\u9fa5](60[0-9]{4}|688[0-9]{3})\b'), 'sh'),
    (re.compile(r'[\u4e00-\u9fa5](00[0-9]{4}|30[0-9]{4})\b'), 'sz'),
    # 独立的6位数字（需结合上下文判断，保守匹配）
    (re.compile(r'\b(60[0-9]{4}|688[0-9]{3})\b'), 'sh'),
    (re.compile(r'\b(00[0-9]{4}|30[0-9]{4})\b'), 'sz'),
]

# 常见的非股票代码6位数字（日期、版本号等）需排除
_NON_STOCK_PATTERNS = [
    re.compile(r'20\d{4}'),  # 20xx年 + 月份，如 202401
    re.compile(r'^\d{6}$'),  # 纯6位数字独立出现时，需结合更多上下文
]


def extract_stock_codes(text: str) -> list[dict]:
    """从文本中提取 A 股股票代码

    Args:
        text: 待分析文本

    Returns:
        股票代码列表，每项包含 code, market, name（如有）
    """
    if not text:
        return []

    found = set()
    results = []

    # 优先匹配带后缀或括号的高置信度模式
    for pattern, market in STOCK_PATTERNS[:4]:
        for m in pattern.finditer(text):
            code = m.group(1)
            if _is_likely_stock_code(code, text):
                key = f"{market}:{code}"
                if key not in found:
                    found.add(key)
                    results.append({
                        "code": code,
                        "market": market,
                        "name": _extract_stock_name_nearby(text, m.start(), m.end()),
                    })

    # 如果没有找到高置信度的，再匹配独立6位数字（但更保守）
    if not results:
        for pattern, market in STOCK_PATTERNS[6:]:
            for m in pattern.finditer(text):
                code = m.group(1)
                if _is_likely_stock_code(code, text):
                    key = f"{market}:{code}"
                    if key not in found:
                        found.add(key)
                        results.append({
                            "code": code,
                            "market": market,
                            "name": _extract_stock_name_nearby(text, m.start(), m.end()),
                        })
            if results:
                break

    return results


def _is_likely_stock_code(code: str, text: str) -> bool:
    """判断一个6位数字是否可能是股票代码"""
    # 排除纯日期格式（如 202401）
    if code.startswith('20') and len(code) == 6:
        # 检查前后是否有日期相关词
        return False
    # 排除版本号（如 1.2.3 中的片段）
    return True


def _extract_stock_name_nearby(text: str, start: int, end: int, window: int = 20) -> Optional[str]:
    """尝试在代码附近提取股票名称"""
    # 向前查找中文公司名
    prefix = text[max(0, start - window):start]
    # 找连续的中文字符（2-8个字符是常见的股票简称长度）
    name_match = re.search(r'([\u4e00-\u9fa5]{2,8})\s*$', prefix)
    if name_match:
        name = name_match.group(1)
        # 排除一些常见的非名称词
        if name not in {'公司', '股份', '集团', '科技', '有限', '公告', '股票', '证券'}:
            return name
    return None


# ============================================================
# 关键词提取（简化版 TF-IDF）
# ============================================================

# 停用词表（金融财经领域常见停用词）
_STOPWORDS = {
    '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一',
    '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有',
    '看', '好', '自己', '这', '他', '她', '它', '们', '那', '些', '什么',
    '公司', '股份', '集团', '有限', '公告', '股票', '证券', '市场', '投资',
    '今日', '昨日', '日前', '目前', '据悉', '报道', '消息', '相关', '表示',
    '通过', '进行', '发布', '公布', '披露', '显示', '同比', '环比',
    '亿元', '万元', '同比增长', '同比下降', '环比增长', '环比下降',
    '中国', '全球', '国内', '国外', '行业', '企业', '产品', '业务',
    '涨', '跌', '上涨', '下跌', '涨幅', '跌幅', '收涨', '收跌',
    '开盘', '收盘', '早盘', '午盘', '尾盘', '盘中', '沪指', '深成指',
    '创业板', '科创板', '主板', '中小板', 'A股', '港股', '美股',
    '点', '个点', '百分点', '百分之', '左右', '约', '近', '超',
    '将', '已', '被', '把', '让', '给', '对', '从', '向', '由', '以',
}


def extract_keywords(text: str, top_n: int = 10) -> list[tuple[str, float]]:
    """从文本中提取关键词

    使用简化的关键词权重算法：
    - 词频统计
    - 停用词过滤
    - 位置加权（标题和首尾段权重更高）
    - 长度加权（2-4字词权重更高）

    Args:
        text: 待分析文本
        top_n: 返回前 N 个关键词

    Returns:
        (关键词, 权重) 列表，按权重降序排列
    """
    if not text:
        return []

    # 提取中文词汇（2-6个字）
    words = re.findall(r'[\u4e00-\u9fa5]{2,6}', text)

    if not words:
        return []

    # 词频统计
    word_freq = Counter(words)

    # 过滤停用词和太短的词
    filtered = {}
    for word, freq in word_freq.items():
        if word in _STOPWORDS:
            continue
        if len(word) < 2:
            continue
        filtered[word] = freq

    if not filtered:
        return []

    # 位置加权：出现在文本开头和结尾的词权重更高
    text_len = len(text)
    position_weights = {}
    for word in filtered:
        positions = [m.start() for m in re.finditer(re.escape(word), text)]
        if positions:
            # 计算位置得分：越靠前或越靠后得分越高
            pos_score = 0
            for pos in positions:
                # 归一化到 0-1，两端得分高
                rel_pos = pos / max(text_len, 1)
                pos_score += 1.0 - abs(rel_pos - 0.5) * 2
            position_weights[word] = pos_score / len(positions)
        else:
            position_weights[word] = 0.5

    # 长度加权：2-4字的词权重最高
    def length_weight(word: str) -> float:
        l = len(word)
        if 2 <= l <= 4:
            return 1.2
        elif 5 <= l <= 6:
            return 1.0
        else:
            return 0.8

    # 综合评分
    max_freq = max(filtered.values()) if filtered else 1
    scores = {}
    for word, freq in filtered.items():
        freq_score = freq / max_freq  # 归一化词频
        pos_score = position_weights.get(word, 0.5)
        len_score = length_weight(word)
        scores[word] = freq_score * 0.5 + pos_score * 0.3 + len_score * 0.2

    # 排序并返回前 N 个
    sorted_keywords = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_keywords[:top_n]


def extract_keywords_simple(text: str, top_n: int = 5) -> list[str]:
    """简化版关键词提取，只返回关键词列表"""
    return [kw for kw, _ in extract_keywords(text, top_n)]


# ============================================================
# 新闻分类（基于规则）
# ============================================================

CATEGORY_KEYWORDS = {
    "宏观经济": ["GDP", "CPI", "PPI", "PMI", "央行", "货币政策", "财政政策", "利率",
                "降准", "降息", "通胀", "通缩", "经济增长", "宏观", "国务院", "发改委"],
    "公司公告": ["公告", "披露", "发布", "业绩预告", "财报", "年报", "季报", "半年报",
                "增持", "减持", "回购", "分红", "配股", "增发", "并购", "重组"],
    "行业动态": ["行业", "产业链", "供应链", "产能", "需求", "供给", "价格", "销量",
                "出货量", "市场份额", "渗透率"],
    "政策监管": ["政策", "监管", "规定", "办法", "条例", "意见", "通知", "证监会",
                "银保监会", "交易所", "处罚", "调查", "立案"],
    "国际市场": ["美股", "港股", "欧股", "美联储", "欧央行", "美元", "欧元", "日元",
                "人民币汇率", "贸易", "关税", "地缘政治"],
    "科技产业": ["AI", "人工智能", "芯片", "半导体", "新能源", "光伏", "储能",
                "电动车", "自动驾驶", "机器人", "生物医药", "创新药"],
    "金融市场": ["股市", "A股", "沪指", "深成指", "创业板", "科创板", "牛市", "熊市",
                "反弹", "回调", "震荡", "成交量", "成交额", "北向资金", "南向资金"],
}


def classify_news(title: str, intro: str = "") -> str:
    """基于关键词规则对新闻进行分类

    Args:
        title: 新闻标题
        intro: 新闻简介/正文

    Returns:
        分类名称
    """
    text = f"{title} {intro}"
    scores = {}

    for category, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            # 标题中出现权重更高
            title_count = title.count(kw)
            intro_count = intro.count(kw)
            score += title_count * 3 + intro_count
        if score > 0:
            scores[category] = score

    if not scores:
        return "其他"

    return max(scores.items(), key=lambda x: x[1])[0]
