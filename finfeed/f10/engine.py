#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""F10 抓取引擎。

提供 14 个 F10 模块的清单与抓取入口：按模块下标抓取同花顺 F10 数据，
渲染为带边框的终端文本，再由 f10data.py 解析为结构化 JSON 供 Web 消费。

本模块不含任何交互式终端界面，只暴露模块清单与抓取能力。
"""

import json
import re

from finfeed.f10 import ths_config
from finfeed.f10.http_client import _get_soup
from finfeed.f10.modules import (
    _fetch_company_soup,
    render_company_detail,
    render_concept,
    render_execs,
    render_finance,
    render_holder_count,
    render_ipo_history,
    render_ipo_info,
    render_latest,
    render_main_compose,
    render_news,
    render_position,
)
from finfeed.f10.parsers.ssr import fetch_legacy
from finfeed.f10.renderers.ascii_table import _text_width, ascii_table, section_header
from finfeed.f10.renderers.terminal import C
from finfeed.f10.utils.cjk import _clip, _wrap_disp
from finfeed.f10.utils.logger import vlog
from finfeed.f10.utils.text import _clean_soup

MODULES = [
    ("公司资料", "legacy", "company.html", ["参股控股"]),
    ("最新动态", "latest", None, []),
    ("股东研究", "legacy", "holder.html", ["十大流通股东", "十大股东", "控股"]),
    ("经营分析", "legacy", "operate.html",
     ["主营介绍", "运营业务数据", "主营构成", "经营评述", "机构评级", "客户", "供应商", "白酒价格"]),
    ("股本结构", "legacy", "equity.html", ["解禁", "股本", "限售", "股东户数", "结构图"]),
    ("资本运作", "legacy", "capital.html",
     ["募集资金", "项目投资", "收购兼并", "股权投资", "参股IPO",
      "股权转让", "关联交易", "质押解冻"]),
    ("盈利预测", "legacy", "worth.html", ["业绩预测", "研报评级", "盈利预测", "机构预测"]),
    ("新闻公告", "notice", None, []),
    ("概念题材", "concept", None, []),
    ("主力持仓", "position", None, []),
    ("财务分析", "finance", None, []),
    ("分红融资", "legacy", "bonus.html", ["分红", "融资", "增发", "配股", "募集"]),
    ("公司大事", "legacy", "event.html", ["大事", "重要事件", "龙虎榜", "大宗交易",
                                         "持股变动", "担保"]),
    ("行业对比", "legacy", "field.html", ["行业地位"]),
]


OPTS = {"all_sections": False}


def _render_violate(code):
    """解析 event.html 的「违规处理」区块 (#violate)。每张 table = 一条处罚记录。"""
    url = f"https://basic.10jqka.com.cn/{code}/event.html"
    sp = _get_soup(url)
    if not sp:
        return ""
    _clean_soup(sp)
    block = sp.find(id="violate")
    if not block:
        return ""
    records = []
    for tb in block.find_all("table"):
        kv = []
        for tr in tb.find_all("tr"):
            for td in tr.find_all(["td", "th"]):
                cell = td.get_text(" ", strip=True)
                if "：" in cell:
                    key, val = cell.split("：", 1)
                    key = key.strip()
                    val = val.strip() or "--"
                    if key and not any(k == key for k, _ in kv):
                        kv.append([key, val])
        if kv:
            records.append(kv)
    if not records:
        return ""
    show_n = min(ths_config.DISPLAY_LIMIT, len(records))
    lines = [section_header(f"违规处理 (最近 {show_n} 条 / 共 {len(records)} 条)")]
    for i, kv in enumerate(records, 1):
        if i > show_n:
            lines.append(f"  {C.DIM}…另有 {len(records) - show_n} 条略去 "
                         f"(--limit 可调整){C.R}")
            break
        lines.append(f"  {C.MAG}◆ 记录 {i}{C.R}")
        lines.append(ascii_table(kv, colcap=62))
    return "\n".join(lines)


def _render_survey(code):
    """解析 event.html 的「机构调研」区块 (#survey)，过滤「查看更多/收起更多」噪音。"""
    url = f"https://basic.10jqka.com.cn/{code}/event.html"
    sp = _get_soup(url)
    if not sp:
        return ""
    _clean_soup(sp)
    block = sp.find(id="survey")
    if not block:
        return ""
    rows = [["机构类别", "调研机构名称"]]
    token_re = re.compile(r"^(?:查看更多|收起更多|收起)\s*|\s*(?:查看更多|收起更多|收起)$")
    for tb in block.find_all("table"):
        for tr in tb.find_all("tr"):
            cells = []
            for td in tr.find_all(["td", "th"]):
                val = token_re.sub("", td.get_text(" ", strip=True)).strip()
                cells.append(val)
            if not any(cells) or cells == rows[0]:
                continue
            rows.append(cells)
    if len(rows) <= 1:
        return ""
    return f"{section_header('机构调研')}\n{ascii_table(rows, colcap=40)}"


def _fetch_module_text(idx, code, name, market_id):
    mod_name, kind, arg, allow = MODULES[idx]
    if OPTS.get("all_sections"):
        allow = None
    if kind == "latest":
        return render_latest(code, market_id)
    elif kind == "concept":
        return render_concept(code, market_id)
    elif kind == "notice":
        return render_news(code, market_id)
    elif kind == "position":
        return render_position(code, market_id)
    elif kind == "finance":
        return render_finance(code, market_id)
    else:
        extra = {"max_rows": 50} if mod_name == "公司资料" else {}
        text = fetch_legacy(code, arg, allow=allow, **extra)
        if mod_name == "公司资料":
            company_soup = _fetch_company_soup(code)
            parts = []
            if company_soup:
                detail = render_company_detail(code, market_id, soup=company_soup)
                if detail:
                    parts.append(f"{section_header('详细情况')}\n{detail}")
                execs = render_execs(code, soup=company_soup)
                if execs:
                    parts.append(f"{section_header('高管介绍')}\n{execs}")
                ipo_parts = []
                ipo = render_ipo_info(code, soup=company_soup)
                if ipo:
                    ipo_parts.append(ipo)
                history = render_ipo_history(code, soup=company_soup)
                if history:
                    ipo_parts.append(f"{section_header('历史沿革', 'sub')}\n{history}")
                if ipo_parts:
                    parts.append(f"{section_header('发行相关')}\n" + "\n\n".join(ipo_parts))
            if text:
                parts.append(text)
            if parts:
                text = "\n\n".join(parts)
        if mod_name == "股东研究":
            holder_count = render_holder_count(code)
            if holder_count:
                text = f"{section_header('股东人数变化')}\n" + holder_count + "\n\n" + (text or "")
        if mod_name == "经营分析":
            main_compose = render_main_compose(code, market_id, periods=1)
            if main_compose and text:
                main_compose_block = f"\n\n{section_header('主营构成分析 (按地区/按产品/按行业)')}\n{main_compose}"
                review_hd = section_header("经营评述")
                if review_hd in text:
                    text = text.replace(review_hd, main_compose_block + "\n\n" + review_hd)
                else:
                    text = text + main_compose_block
            elif main_compose:
                text = (text or "") + f"\n{section_header('主营构成分析 (按地区/按产品/按行业)')}\n{main_compose}"
        if mod_name == "公司大事":
            try:
                url = f"https://basic.10jqka.com.cn/{code}/interactive.html"
                sp = _get_soup(url)
                if sp:
                    _clean_soup(sp)
                    for d in sp.find_all(["div", "p"]):
                        txt = d.get_text(strip=True)
                        if txt.startswith("[{") or txt.startswith('[{"'):
                            try:
                                qas = json.loads(txt)
                            except json.JSONDecodeError:
                                continue
                            if not isinstance(qas, list):
                                continue
                            tw = _text_width()
                            vfill = max(1, tw - 2)
                            show_n = min(len(qas), ths_config.DISPLAY_LIMIT)
                            note = f" / 共 {len(qas)} 条" if len(qas) > show_n else ""
                            lines = [section_header(
                                f"投资者互动列表 (最近 {show_n} 条{note})")]
                            for qa in qas[:show_n]:
                                date = f"{qa.get('year','')}-{qa.get('month','')}-{qa.get('day','')}"
                                asker = qa.get("asker", "")
                                question = qa.get("question", "")
                                reply = qa.get("reply", "")
                                lines.append(f"  {C.DIM}{date}{C.R}  {C.GRN}{asker}{C.R}")
                                for seg in _wrap_disp(f"问: {question}", vfill):
                                    lines.append(f"  {seg}")
                                if reply:
                                    r = _clip(reply, vfill * 6)
                                    for seg in _wrap_disp(f"答: {r}", vfill):
                                        lines.append(f"  {seg}")
                                lines.append("")
                            if lines:
                                text = (text or "") + "\n" + "\n".join(lines)
                            break
            except Exception as e:
                vlog(f"互动易解析异常 ({code}): {e}")
            violate = _render_violate(code)
            if violate:
                text = (text or "") + "\n\n" + violate
            survey = _render_survey(code)
            if survey:
                text = (text or "") + "\n\n" + survey
        if mod_name == "行业对比":
            try:
                url = f"https://basic.10jqka.com.cn/{code}/field.html"
                sp = _get_soup(url)
                if sp:
                    news_div = sp.find("div", class_=lambda c: c and "newslist" in (c or ""))
                    if news_div:
                        full_text = news_div.get_text(separator=" ", strip=True)
                        items = []
                        prev_date = None
                        last_end = 0
                        for m in re.finditer(r"\d{2}/\d{2}\s+\d{2}:\d{2}", full_text):
                            if prev_date:
                                news_title = full_text[last_end:m.start()].strip()
                                news_title = re.sub(r"\s*查看全文>>\s*", " ", news_title)
                                news_title = re.sub(r"\s+", " ", news_title).strip()
                                if news_title:
                                    items.append((prev_date, news_title))
                            prev_date = m.group()
                            last_end = m.end()
                        if prev_date and last_end > 0:
                            news_title = full_text[last_end:].strip()
                            news_title = re.sub(r"\s*查看全文>>\s*", " ", news_title)
                            news_title = re.sub(r"\s+", " ", news_title).strip()
                            if news_title:
                                items.append((prev_date, news_title))
                        if items:
                            from finfeed.f10.renderers.ascii_table import ascii_table
                            show_n = min(len(items), ths_config.DISPLAY_LIMIT)
                            table_rows = [["日期", "行业新闻标题"]]
                            for date, title_text in items[:show_n]:
                                if len(title_text) > 80:
                                    title_text = title_text[:77] + "..."
                                table_rows.append([date, title_text])
                            news_table = ascii_table(table_rows, colcap=55)
                            note = (f" (前 {show_n} 条 / 共 {len(items)} 条)"
                                    if len(items) > show_n else "")
                            text = (text or "") + \
                                f"\n{section_header(f'行业新闻{note}')}\n{news_table}"
            except Exception as e:
                vlog(f"行业新闻解析异常 ({code}): {e}")
        return text
