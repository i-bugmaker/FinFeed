#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告呈现装饰（展示层，不依赖模型是否守格式）。

目标：让 AI 生成的复盘报告在网页里更易读——
  1. 给 Markdown 章节标题（## / ###）按关键词自动加贴切的 emoji 图标；
  2. 把模型偶尔写出的「一、核心结论」「**重点事件**」这类散文式分段标记，
     规范成真正的 Markdown 标题，形成清晰结构；
  3. 不破坏表格 / 代码块 / 列表等既有结构。

纯展示增强，不改变任何统计数字。
"""

import re
from typing import List, Optional

# 关键词 -> emoji，越具体越靠前（先匹配长词）
_EMOJI_ORDER: List[tuple] = [
    ("数据概览", "📊"),
    ("核心结论", "💡"),
    ("总体结论", "💡"),
    ("总体判断", "💡"),
    ("结论", "💡"),
    ("重点事件", "📌"),
    ("重要事件", "📌"),
    ("事件", "📌"),
    ("主题聚类", "🏷️"),
    ("主题分析", "🏷️"),
    ("主题", "🏷️"),
    ("政策", "📋"),
    ("监管", "📋"),
    ("行业", "🏭"),
    ("个股", "🏭"),
    ("板块", "🏭"),
    ("海外", "🌍"),
    ("宏观", "🌐"),
    ("全球", "🌐"),
    ("市场情绪", "💭"),
    ("情绪", "💭"),
    ("风险", "⚠️"),
    ("提示", "⚠️"),
    ("后市", "🔭"),
    ("关注", "🔭"),
    ("展望", "🔭"),
    ("资金", "💰"),
    ("市场", "📈"),
    ("行情", "📈"),
    ("摘要", "📝"),
    ("总结", "📝"),
]

# 用于「KEYWORD：内容」内联拆分的章节关键词（仅这些会被提升为标题）
_SECTION_KEYWORDS = [
    "核心结论", "总体结论", "总体判断", "重点事件", "重要事件", "主题聚类", "主题分析",
    "政策与监管", "政策监管", "行业与个股", "行业动向", "海外与宏观", "海外市场",
    "情绪研判", "市场情绪", "风险提示", "后市关注", "数据概览", "摘要", "总结",
]

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2B00-\u2BFF\uFE0F]"
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*(?:[一二三四五六七八九十]+|\d{1,2})[.、.、]\s*(.+)$")
_BOLD_LINE_RE = re.compile(r"^\*\*\s*(.+?)\s*\*\*\s*$")
_INLINE_SECTION_RE = re.compile(
    r"^\s*(?:" + "|".join(re.escape(k) for k in _SECTION_KEYWORDS) + r")\s*[：:：]\s*(.*)$"
)


def _has_emoji(text: str) -> bool:
    return bool(_EMOJI_RE.search(text or ""))


def _emoji_for(title: str) -> Optional[str]:
    if not title:
        return None
    for kw, em in _EMOJI_ORDER:
        if kw in title:
            return em
    return None


def decorate_report_body(text: str) -> str:
    """给标题加 emoji，并把散文式分段标记规范为 Markdown 标题。"""
    if not text:
        return text
    lines = text.replace("\r\n", "\n").split("\n")
    out: List[str] = []
    in_code = False

    for raw in lines:
        s = raw.strip()
        # 代码块：原样透传
        if s.startswith("```"):
            out.append(raw)
            in_code = not in_code
            continue
        if in_code:
            out.append(raw)
            continue
        if s == "":
            out.append(raw)
            continue

        # 1) 已有 Markdown 标题：补 emoji（若缺失）
        m = _HEADING_RE.match(s)
        if m:
            title = m.group(2).strip()
            if _has_emoji(title):
                out.append(raw)
            else:
                em = _emoji_for(title)
                out.append(f"{m.group(1)} {em} {title}".strip() if em else raw)
            continue

        # 2) 编号分段（一、核心结论 / 1. 重点事件）：含章节关键词才提升为标题
        nm = _NUMBERED_RE.match(s)
        if nm:
            title = nm.group(1).strip()
            em = _emoji_for(title)
            if em:
                out.append(f"## {em} {title}")
                continue

        # 3) 整行加粗（**重点事件**）：含关键词则提升为标题
        bm = _BOLD_LINE_RE.match(s)
        if bm:
            title = bm.group(1).strip()
            em = _emoji_for(title)
            if em:
                out.append(f"### {em} {title}")
                continue

        # 4) 内联「关键词：内容」：拆成标题 + 段落
        im = _INLINE_SECTION_RE.match(s)
        if im:
            kw = im.group(0).split("：")[0].split(":")[0].strip()
            rest = im.group(1).strip()
            em = _emoji_for(kw)
            out.append(f"## {em} {kw}".strip() if em else f"## {kw}")
            if rest:
                out.append(rest)
            continue

        out.append(raw)

    # 折叠多余连续空行（保留最多一个），避免装饰后产生大段空白
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return cleaned


if __name__ == "__main__":
    sample = """## 一、核心结论
市场整体震荡。半导体板块走强。
**重点事件**
某龙头发布新品。
核心结论：风险偏好回升。
## 数据概览
| 信源 | 条数 |
| --- | --- |
| 东方财富 | 10 |"""
    print(decorate_report_body(sample))
