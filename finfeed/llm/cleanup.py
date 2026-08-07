#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模型原始输出后处理。

部分模型（尤其推理型/免费模型）会在正文开头输出"好的，用户要求……"
"面对这个问题，我的任务是……"这类内心独白，或把整段分析写成无空行分隔的
连续散文。本模块在存档前做轻量清洗，使前端 Markdown 渲染器能呈现为结构清晰、
可读性高的报告，而不依赖模型严格遵守格式约束。

处理策略：
  1. 删除过程性/独白整行（出现在任何位置都删，属于噪声）。
  2. 丢弃原始空行后，对散文行在上下方补一个空行，形成独立段落；
     标题/列表/表格/引用等结构行保持相邻，交给渲染器正常解析。
  3. 折叠多余空行。
"""

import logging
import re
from typing import List

logger = logging.getLogger("news_monitor")

# 过程性/独白开头，命中则整行删除
_PREAMBLE_PATTERNS = [
    r'^\s*好的[，,]\s*用户要求',
    r'^\s*好的[，,]\s*',
    r'^\s*没问题[，,，]?\s*',
    r'^\s*当然可以[，,，]?\s*',
    r'^\s*面对这个问题',
    r'^\s*首先[，,，]?\s*我',
    r'^\s*我的任务是',
    r'^\s*用户要求我',
    r'^\s*根据要求[，,，]?\s*',
    r'^\s*根据指令[，,，]?\s*',
    r'^\s*让我(来|先|梳理|整理|分析)',
    r'^\s*现在我来',
    r'^\s*下面(我|是|给)',
    r'^\s*作为.*?[，,]\s*我将',
    r'^\s*我需要(撰写|生成|整理|完成)',
    r'^\s*我将(为|根|按)',
    r'^\s*先整理',
    r'^\s*接下来[，,，]?\s*',
]
_PREAMBLE_RE = [re.compile(p) for p in _PREAMBLE_PATTERNS]


def _is_structural(line: str) -> bool:
    """判断是否为 Markdown 结构行（保持原样、不与上下合并）。"""
    s = line.strip()
    if not s:
        return False
    if re.match(r'^#{1,6}\s', s):
        return True
    if re.match(r'^[-*+]\s+', s):
        return True
    if re.match(r'^\d+[.、]\s+', s):
        return True
    if s.startswith('>'):
        return True
    if re.match(r'^\s*([-*_])(\s*\1){2,}\s*$', s):
        return True
    if s.startswith('|') and s.endswith('|'):
        return True
    if s.startswith('```'):
        return True
    return False


def clean_report_body(text: str) -> str:
    """清洗模型正文：去独白、按句断成可读段落。"""
    if not text:
        return text
    lines = text.replace('\r\n', '\n').split('\n')
    out: List[str] = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue  # 丢弃原始空行，稍后按需补回
        # 删除过程性独白行
        if any(rx.match(s) for rx in _PREAMBLE_RE):
            continue
        if _is_structural(s):
            out.append(s)
        else:
            # 散文：与上一行之间补一个空行，形成独立段落
            if out and out[-1] != '':
                out.append('')
            out.append(s)
    cleaned = '\n'.join(out).strip()
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # 折叠多余空行
    return cleaned


if __name__ == '__main__':
    import sqlite3
    con = sqlite3.connect('finfeed/news_monitor.db')
    cur = con.cursor()
    cur.execute("SELECT substr(content, instr(content, '---\n\n') + 5) FROM llm_reports ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    con.close()
    if row and row[0]:
        logger.info(clean_report_body(row[0])[:1500])
