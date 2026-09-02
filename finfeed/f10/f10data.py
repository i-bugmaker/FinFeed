#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""THS-F10-Web 数据层。

职责：把 F10 抓取引擎（engine / modules / renderers）渲染出的终端文本，
解析为供 Web 前端消费的结构化 JSON（章节 -> 表格 / 键值对 / 文本），
并提供带 TTL 缓存的模块抓取与股票搜索。

抓取引擎已是本项目自有模块（engine.py、modules/、renderers/、http_client.py），
本模块不再承担任何"桥接外部目录"的职责，只负责数据转换与缓存。

对外主要接口:
    suggest(keyword)                  股票搜索建议（统一走 api.eastmoney）
    resolve(keyword)                  精确解析一只股票
    fetch_module(idx, code, mid)      抓取一个 F10 模块并返回结构化 JSON
    meta()                            模块清单 / 版本号等元信息
"""

import json
import os
import re
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))

_DEFAULT_CFG = {
    "port": 8653,
    "cache_ttl": 900,
    "display_limit": 100,
}


def _load_cfg():
    cfg = dict(_DEFAULT_CFG)
    path = os.path.join(_HERE, "config.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:  # 配置损坏时退回默认
            print(f"[f10data] config.json 读取失败: {e}", file=sys.stderr)
    return cfg


CFG = _load_cfg()

# ---- 初始化渲染环境：无 ANSI 颜色、固定宽度，终端文本才可稳定解析 ----
from finfeed.f10.renderers.terminal import disable_color  # noqa: E402

disable_color()

from finfeed.f10.renderers.ascii_table import _is_numeric_col, set_term_width  # noqa: E402

set_term_width(150)

from finfeed.f10 import ths_config  # noqa: E402

ths_config.DISPLAY_LIMIT = max(1, int(CFG.get("display_limit", 30)))

from finfeed.f10 import engine  # noqa: E402
from finfeed.f10.engine import MODULES  # noqa: E402
from finfeed.f10.utils.cjk import wlen  # noqa: E402

# Web 端默认展示页面全部章节，信息不遗漏
engine.OPTS["all_sections"] = True

from finfeed.f10.api.eastmoney import (  # noqa: E402
    _normalize_suggest_name,
    market_id_from_code,
    suggest_rows,
)

# 搜索

def suggest(keyword):
    """返回 A 股搜索建议列表 [{code,name,market_id,type}]，最多 8 条。

    搜索来源统一走 api.eastmoney.suggest_rows —— URL、token 与 A 股过滤规则
    只在该处定义一次。Web 搜索要求交互响应速度，故覆盖限速参数。
    """
    rows = suggest_rows(keyword, count=8, timeout=10,
                        min_delay=0.2, max_delay=0.4, _retries=1)
    out, seen = [], set()
    for x in rows:
        code = (x.get("Code") or "").strip()
        name = _normalize_suggest_name(x.get("Name") or "")
        if code in seen:
            continue
        seen.add(code)
        out.append({
            "code": code,
            "name": name,
            "market_id": market_id_from_code(code, x.get("SecurityTypeName", "")),
            "type": x.get("SecurityTypeName", ""),
        })
        if len(out) >= 8:
            break
    return out


def resolve(keyword):
    """精确解析一只股票，返回 {code,name,market_id} 或 None。"""
    rows = suggest(keyword)
    kw = (keyword or "").strip().lower()
    for x in rows:
        if x["code"] == kw:
            return x
    for x in rows:
        if x["name"] == (keyword or "").strip():
            return x
    return rows[0] if len(rows) == 1 else None


# 终端文本 -> 结构化数据 解析器

_SECTION_RE = re.compile(r"^(▸|●|■)\s+(.+?)\s*$")
_KV_RE = re.compile(r"^(\s*)(\S.*?)(?:\s{2,}(\S.*))?$")
_COLON_KV_RE = re.compile(r"^([\u4e00-\u9fffA-Za-z0-9*]{1,10})[:：]\s*(.*)$")
_BULLET_RE = re.compile(r"^[·•‧]\s*(.*)$")
_SUBHEAD_RE = re.compile(r"^\s{0,6}◆\s*(.+?)\s*$")
_DATE_KV_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s{2,}(\S.*)$")
_DIVIDER_RE = re.compile(r"^[┄┈─━═~～]{6,}$")

_TBL_TOP = "┌┏╔"
_TBL_BOT = "└┗╚"
_TBL_SEP = "├┣╠"
_TBL_ROW = "│┃║"
_H_CHARS = "─━═"

_MID_END = "，、；：,;:（(“《【…·%‰-—/"


def _border_spans(line):
    """从表格边框线提取各列的 (起始显示列, 宽度)。"""
    spans = []
    run = 0
    for ch in line:
        if ch in _H_CHARS:
            run += 1
        else:
            if run:
                spans.append(run)
            run = 0
    if run:
        spans.append(run)
    offs = []
    pos = 1  # 首字符是 ┌/├/└
    for w in spans:
        offs.append((pos, w))
        pos += w + 1
    return offs


def _cells_by_width(line, spans):
    """按显示宽度把表格内容行切分为单元格。"""
    n = len(spans)
    out = [[] for _ in range(n)]
    pos = 0
    si = 0
    for ch in line:
        cw = wlen(ch)
        while si < n - 1 and pos >= spans[si][0] + spans[si][1]:
            si += 1
        if spans[si][0] <= pos < spans[si][0] + spans[si][1]:
            out[si].append(ch)
        pos += cw
    return ["".join(c).strip() for c in out]


def _join_cell(a, b):
    """合并被折行的单元格文本。"""
    if not a:
        return b
    if not b:
        return a
    if a[-1].isdigit() and b[0].isdigit():
        return a + b  # 数字被从中间折断（如日期 2026-06-30）
    if a[-1].isascii() and a[-1].isalnum() and b[0].isascii() and b[0].isalnum():
        return a + " " + b  # 英文单词折行
    return a + b


def _merge_table_lines(lines, spans):
    """把若干物理行合并为逻辑行（处理单元格内折行）。

    判定规则：折行续行只会出现在上一行"占满列宽"的列上，
    且其余列为空白（真实数据行的空单元格渲染为 --，可区分）。
    """
    logical = []  # [cells]
    open_full = set()  # 当前行中占满列宽、可能继续折行的列
    for ln in lines:
        if not ln or ln[0] not in _TBL_ROW:
            continue
        cells = _cells_by_width(ln, spans)
        full = set()
        for i, (s, w) in enumerate(spans):
            if i < len(cells) and cells[i] and wlen(cells[i]) >= w - 2:
                full.add(i)
        nonblank = {i for i, c in enumerate(cells) if c}
        if open_full and nonblank and nonblank <= open_full:
            for i, c in enumerate(cells):
                if c:
                    logical[-1][i] = _join_cell(logical[-1][i], c)
            open_full = full if full else set()
            if not full:
                open_full = set()
        else:
            logical.append(cells)
            open_full = set(full)
    return logical


def _parse_table(lines):
    """把表格物理行块解析为 {type:'table', header, rows, num}。"""
    top_idx = next((i for i, ln in enumerate(lines) if ln and ln[0] in _TBL_TOP), None)
    if top_idx is None:
        return None
    spans = _border_spans(lines[top_idx])
    if not spans:
        return None
    sep_idx = next((i for i, ln in enumerate(lines)
                    if i > top_idx and ln and ln[0] in _TBL_SEP), None)
    header_lines = [ln for ln in lines[top_idx + 1:sep_idx] if ln and ln[0] in _TBL_ROW]
    body_start = sep_idx + 1 if sep_idx is not None else top_idx + 1
    data_lines = [ln for ln in lines[body_start:] if ln and ln[0] in _TBL_ROW]
    header_rows = _merge_table_lines(header_lines, spans)
    rows = _merge_table_lines(data_lines, spans)
    if not header_rows or not rows:
        return None  # 只有表头没有数据行的空表（如主营构成的 SSR 占位），直接丢弃
    # 表头逻辑上是一行，被折行时 _merge_table_lines 会给出多行，逐列拼接
    header = list(header_rows[0])
    for extra in header_rows[1:]:
        header = [_join_cell(a, b) for a, b in zip(header, extra)]
    ncol = len(header)
    header = header[:ncol]
    fixed = []
    for r in rows:
        if len(r) < ncol:
            r = r + [""] * (ncol - len(r))
        fixed.append(r[:ncol])
    numeric = []
    probe = [header] + fixed
    for i in range(ncol):
        try:
            numeric.append(bool(_is_numeric_col(probe, i)))
        except Exception:
            numeric.append(False)
    return {"type": "table", "header": header, "rows": fixed, "num": numeric}


def _split_table_blocks(lines):
    """把章节内的物理行切分为 ('table', 行块) / ('lines', 普通行) 序列。"""
    blocks = []
    buf = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln and ln[0] in _TBL_TOP:
            j = i
            while j < len(lines) and not (lines[j] and lines[j][0] in _TBL_BOT):
                j += 1
            if j < len(lines):
                j += 1
            if any(x.strip() for x in buf):
                blocks.append(("lines", buf))
                buf = []
            blocks.append(("table", lines[i:j]))
            i = j
        else:
            buf.append(ln)
            i += 1
    if any(x.strip() for x in buf):
        blocks.append(("lines", buf))
    return blocks


def _cjk_join(a, b):
    if not a:
        return b
    if not b:
        return a
    if a[-1].isdigit() and b[0].isdigit():
        return a + b
    if a[-1].isascii() and a[-1].isalnum() and b[0].isascii() and b[0].isalnum():
        return a + " " + b
    return a + b


def _incomplete(text):
    """段落是否未结束（结尾是句中标点，或被按宽折断）。"""
    if not text:
        return False
    if text[-1] in _MID_END:
        return True
    return wlen(text) >= 140


def _parse_lines(lines):
    """把普通文本行解析为 p / li / kv / h / meta / div 混合条目序列。"""
    items = []

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            items.append({"t": "br"})
            continue
        s = line.strip()
        indent = len(line) - len(line.lstrip(" "))

        if _DIVIDER_RE.match(s):
            items.append({"t": "div"})
            continue

        m = _SUBHEAD_RE.match(line)
        if m and "  " not in s:
            items.append({"t": "h", "text": m.group(1)})
            continue

        m = _DATE_KV_RE.match(s)
        if m:
            items.append({"t": "kv", "k": m.group(1), "v": m.group(2), "sub": True})
            continue

        m = _BULLET_RE.match(s)
        if m and indent > 0:
            items.append({"t": "li", "text": m.group(1), "indent": indent})
            continue

        m = _KV_RE.match(line)
        if m and m.group(3) and indent <= 6 and len(m.group(2)) <= 24:
            segs = [x for x in re.split(r"\s{2,}", s) if x]
            if len(segs) >= 3:
                # 一行里排布多个「标签 数值」属性（如概念板块行情行）
                items.append({"t": "meta", "text": s, "indent": indent})
            else:
                items.append({"t": "kv", "k": m.group(2).strip(),
                              "v": m.group(3).strip(), "indent": indent})
            continue

        m = _COLON_KV_RE.match(s)
        if m and len(s) <= 90:
            items.append({"t": "kv", "k": m.group(1), "v": m.group(2),
                          "sub": True, "indent": indent})
            continue

        # 无模式行：续行 或 新段落。
        # 折行续行的判定：上行以句中标点结尾、上行/本行几乎占满版面宽度，
        # 或本行比子级键值行缩进深得多（如「龙头:」的多条领涨股）。
        prev = items[-1] if items else None
        if prev is not None and prev["t"] == "br":
            items.pop()
            prev = items[-1] if items else None
        if prev is None:
            items.append({"t": "p", "text": s, "indent": indent,
                          "full": wlen(s) >= 140})
            continue
        if prev["t"] == "p":
            if prev["text"][-1] in _MID_END or wlen(s) >= 140 or prev.get("full"):
                prev["full"] = wlen(s) >= 140
                prev["text"] = _cjk_join(prev["text"], s)
                continue
            items.append({"t": "p", "text": s, "indent": indent,
                          "full": wlen(s) >= 140})
            continue
        if prev["t"] == "kv":
            if not prev.get("sub") and indent >= 2:
                prev["v"] = _cjk_join(prev["v"], s) if prev["v"] else s
                continue
            if prev.get("sub") and prev.get("k") in ("问", "答"):
                # 投资者互动问答的折行续行，直接拼回原文
                prev["v"] = _cjk_join(prev["v"], s) if prev["v"] else s
                continue
            if prev.get("sub") and indent > prev.get("indent", 0) + 2:
                # 多条并列子项（如「龙头:」的领涨股），按行保留
                prev["v"] = (prev["v"] + "\n" + s) if prev["v"] else s
                continue
        items.append({"t": "p", "text": s, "indent": indent,
                      "full": wlen(s) >= 140})

    cleaned = []
    for it in items:
        if it["t"] == "br" and (not cleaned or cleaned[-1]["t"] == "br"):
            continue
        cleaned.append(it)
    while cleaned and cleaned[-1]["t"] == "br":
        cleaned.pop()
    return cleaned


def _group_blocks(items):
    """把条目序列分组为 blocks：连续 kv 成 kv 块，p/li/h/meta 并入 text 块。"""
    blocks = []
    cur_kv = []

    def flush_kv():
        if not cur_kv:
            return
        blocks.append({"type": "kv", "items": list(cur_kv)})
        cur_kv.clear()

    for it in items:
        if it["t"] == "kv" and not it.get("sub"):
            cur_kv.append(it)
            continue
        if it["t"] == "kv" and it.get("sub") and cur_kv:
            cur_kv.append(it)
            continue
        flush_kv()
        if it["t"] == "br":
            continue
        if it["t"] == "div":
            blocks.append({"type": "div"})
            continue
        if blocks and blocks[-1]["type"] == "text":
            blocks[-1]["items"].append(it)
        else:
            blocks.append({"type": "text", "items": [it]})
    flush_kv()
    return blocks


def _humanize_diagnosis(sec):
    """财务诊断章节：把「行业排名 x/y N.本期…」长文本拆成带排名徽标的条目。"""
    parts = []
    for b in sec["blocks"]:
        if b["type"] == "text":
            for it in b["items"]:
                if it["t"] == "p":
                    parts.append(it["text"])
    text = " ".join(parts)
    if "行业排名" not in text:
        return sec
    t = re.sub(r"\s*行业排名\s*(\d+/\d+)\s*", "\n@R@\\1@\n", text)
    items = []
    cur_rank = ""
    for chunk in t.split("\n"):
        chunk = chunk.strip()
        m = re.match(r"@R@([\d/]+)@(.*)$", chunk)
        if m:
            cur_rank = m.group(1)
            chunk = m.group(2)
        if not chunk:
            continue
        for seg in re.split(r"(?=\d+\.(?:本期|中报))", chunk):
            seg = seg.strip().strip(",")
            if seg:
                items.append({"t": "rank", "rank": cur_rank, "text": seg})
    if not items:
        return sec
    return {"title": sec["title"], "level": sec["level"],
            "blocks": [{"type": "text", "items": items}]}


def _normalize_theme_points(sec):
    """题材要点：全部拍平为「标签 + 内容」便签序列，任何文本都不丢弃。

    数据源格式不统一：接口返回「要点N：标题」键值行，页面兜底则可能是
    纯文本段落开头的要点。这里把键值与文本段落按顺序合并成统一的便签序列。
    """
    items = []

    def absorb_text(b):
        # 文本块里也可能混有单个键值项（如「要点一  拟购买…」），一并收入
        for it in b["items"]:
            if it["t"] == "kv":
                it["sub"] = True
                items.append(it)
        extra = " ".join(
            it.get("text", "") for it in b["items"]
            if it["t"] in ("p", "meta")
        ).strip()
        if not extra:
            return
        if items:
            last = items[-1]
            last["v"] = _cjk_join(last.get("v", ""), extra)
        else:
            items.append({"t": "kv", "k": "", "v": extra, "sub": True})

    for b in sec["blocks"]:
        if b["type"] == "kv":
            for it in b["items"]:
                it["sub"] = True
                items.append(it)
        elif b["type"] == "text":
            absorb_text(b)

    if not items:
        return sec
    return {"title": sec["title"], "level": sec["level"],
            "blocks": [{"type": "kv", "items": items}]}


def parse_module_text(text):
    """把引擎渲染的一个模块文本解析为 sections 列表。"""
    sections = []
    cur = None
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        m = _SECTION_RE.match(line)
        if m:
            title = re.sub(r"^X(?=[\u4e00-\u9fff])", "", m.group(2).strip())
            cur = {"title": title,
                   "level": 2 if m.group(1) in "▸■" else 3, "lines": []}
            sections.append(cur)
            continue
        if cur is None:
            if not line.strip():
                continue
            cur = {"title": "", "level": 2, "lines": []}
            sections.append(cur)
        cur["lines"].append(line)

    out = []
    for sec in sections:
        blocks = []
        for kind, payload in _split_table_blocks(sec["lines"]):
            if kind == "table":
                tb = _parse_table(payload)
                if tb:
                    blocks.append(tb)
                rest = [ln for ln in payload
                        if ln.strip() and ln[0] not in _TBL_ROW + _TBL_TOP + _TBL_BOT + _TBL_SEP]
                if rest:
                    blocks.extend(_group_blocks(_parse_lines(rest)))
            else:
                blocks.extend(_group_blocks(_parse_lines(payload)))
        merged = []
        for b in blocks:
            if b["type"] == "text" and merged and merged[-1]["type"] == "text":
                merged[-1]["items"].extend(b["items"])
            else:
                merged.append(b)
        while merged and merged[0]["type"] == "div":
            merged.pop(0)
        while merged and merged[-1]["type"] == "div":
            merged.pop()
        if merged:
            out.append({"title": sec["title"], "level": sec["level"], "blocks": merged})
    # 「?」是 company.html 上的无名小节（内容与高管介绍重复），丢弃
    out = [s for s in out if s["title"] != "?"]
    out = [_humanize_diagnosis(s) if "财务诊断" in s["title"] else s for s in out]
    out = [_normalize_theme_points(s) if s["title"].startswith("题材要点") else s
           for s in out]
    return out


# 模块抓取（带缓存 + 全局串行锁，避免并发抓取触发风控）

_fetch_lock = threading.Lock()
_cache = {}


class ModuleFetchError(Exception):
    pass


def fetch_module(idx, code, mid, refresh=False):
    """抓取一个模块并返回结构化 payload（带 TTL 缓存）。"""
    if not isinstance(idx, int) or not (0 <= idx < len(MODULES)):
        raise ModuleFetchError(f"模块编号越界: {idx}")
    if not re.match(r"^\d{6}$", code or ""):
        raise ModuleFetchError(f"无效的股票代码: {code}")
    key = f"{code}:{idx}"
    with _fetch_lock:
        ent = _cache.get(key)
        if ent and not refresh and time.time() - ent["ts"] < CFG["cache_ttl"]:
            payload = dict(ent["payload"])
            payload["cached"] = True
            return payload
        try:
            text = engine._fetch_module_text(idx, code, "", str(mid))
        except Exception as e:
            raise ModuleFetchError(f"抓取失败: {e}") from e
        if text is None:
            text = ""
        payload = {
            "ok": True,
            "code": code,
            "market_id": str(mid),
            "module_index": idx,
            "module": MODULES[idx][0],
            "fetched_at": int(time.time()),
            "sections": parse_module_text(text),
            "empty": not (text or "").strip(),
        }
        _cache[key] = {"ts": time.time(), "payload": payload}
        return payload


def meta():
    return {
        "version": getattr(ths_config, "__version__", ""),
        "modules": [{"index": i, "name": m[0]} for i, m in enumerate(MODULES)],
        "cache_ttl": CFG["cache_ttl"],
    }


def clear_cache():
    with _fetch_lock:
        _cache.clear()


if __name__ == "__main__":
    # 自检: python f10data.py sample1.txt sample2.txt ...
    for p in sys.argv[1:]:
        with open(p, encoding="utf-8") as f:
            secs = parse_module_text(f.read())
        print(f"== {os.path.basename(p)}: {len(secs)} sections")
        for s in secs:
            kinds = []
            for b in s["blocks"]:
                if b["type"] == "kv":
                    kinds.append(f"kv{len(b['items'])}")
                elif b["type"] == "table":
                    kinds.append(f"tbl{len(b['rows'])}x{len(b['header'])}")
                elif b["type"] == "text":
                    kinds.append("txt" + str(len(b["items"])))
                else:
                    kinds.append(b["type"])
            print(f"   [{s['title']}] " + " ".join(kinds))
