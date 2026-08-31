import html as _html
import json
import re
import sys

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("缺少依赖: 请先运行  pip install requests beautifulsoup4")

from finfeed.f10.http_client import _get_soup, safe_get
from finfeed.f10.modules.concept import fuyao_get
from finfeed.f10.modules.news import _ts2date, basicapi_get
from finfeed.f10.renderers.ascii_table import _text_width, ascii_table, section_header
from finfeed.f10.renderers.terminal import C
from finfeed.f10.utils.cjk import _clip, _pad, _wrap_disp, wlen
from finfeed.f10.utils.text import _clean_cell, _clean_soup, _norm_rendered_text


def _extract_flash_data(soup_box):
    entries = []

    for span in list(soup_box.find_all("span",
                      class_=lambda c: c and "falshData" in c)):
        raw = span.get_text(strip=True)
        if not raw:
            span.decompose()
            continue

        indicator = ""
        prev_td = span.find_previous("td")
        if prev_td:
            td_text = prev_td.get_text(" ", strip=True)
            before_json = re.split(r'\[\[\[', td_text, maxsplit=1)[0].strip()
            m = re.match(r'^([^\d\-．%]+)', before_json)
            if m:
                indicator = m.group(1).strip().rstrip('：:')

        span.decompose()

        try:
            data = json.loads(raw)
            series = data[0]
            labels_raw = data[1]
            unit = data[2] if len(data) > 2 else ""
        except (json.JSONDecodeError, IndexError, TypeError):
            continue

        values = [str(s[1]) for s in series
                  if isinstance(s, (list, tuple)) and len(s) > 1]
        labels = [str(item[1]) for item in labels_raw
                  if isinstance(item, (list, tuple)) and len(item) > 1]
        if not values or not labels:
            continue

        if not indicator:
            indicator = f"指标{len(entries) + 1}"

        entries.append((indicator, values, labels, unit))

    if not entries:
        return None

    labels = entries[0][2]
    start = 1 if len(labels) > 1 else 0

    header = ["指标"] + labels[start:]
    rows = [header]
    for indicator, values, _, unit in entries:
        label = f"{indicator}({unit})" if unit else indicator
        row = [label]
        row.extend(values[start:])
        rows.append(row)

    return rows


def _trim_cell_text(s):
    s = str(s)
    s = re.sub(r'\[\[\[.*', '', s)
    s = re.sub(r'查看(?:明细|详情)>>', '', s)
    s = re.sub(
        r'(?:每股收益|每股净资产|每股资本公积金|每股未分配利润'
        r'|每股经营现金流|营业总收入|净利润|毛利率|净资产收益率'
        r'|质押股份占A股总股本比|总质押股份数量)单位[：:][^\s；;，,，]*',
        '', s)
    s = re.sub(r'查看更多>>|更多>>', '', s)
    s = re.sub(r'^对比>>.*?$', '', s, flags=re.MULTILINE)
    s = re.sub(r'详情>>\s*', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _clean_chart_data(text):
    text = re.sub(r'[\[\]\"\']', '', text)
    text = re.sub(r'\\u[0-9a-fA-F]{4}',
                  lambda m: chr(int(m.group(0)[2:], 16)), text)
    text = re.sub(r',{2,}', ',', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _extract_mbox_paragraphs(box):
    paras = []
    bd = box.find("div", class_="bd")
    target = bd if bd else box
    for p in target.find_all("p"):
        if p.find_parent("table"):
            continue
        text = p.get_text(strip=True)
        if not text or len(text) < 4:
            continue
        if any(kw in text for kw in ("免责声明", "查看更多", "更多>>", "详情>>", "提示：")):
            continue
        paras.append(text)
    return "\n\n".join(paras)


def _extract_box_tables(box):
    tables = []
    for tb in box.find_all("table"):
        rows = []
        for tr in tb.find_all("tr"):
            cells = [_clean_cell(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def _fetch_popular_rank(code):
    """同花顺 F10 市场/行业人气排名。返回 dict 或 None(失败不阻塞)。"""
    try:
        mk = safe_get(
            f"https://basic.10jqka.com.cn/mapp/{code}/a_focus_rank.json",
            headers={"Referer": "https://basic.10jqka.com.cn/"}, timeout=15)
        ik = safe_get(
            f"https://basic.10jqka.com.cn/mapp/{code}/a_industry_focus_rank.json",
            headers={"Referer": "https://basic.10jqka.com.cn/"}, timeout=15)
        if mk.status_code != 200 or ik.status_code != 200:
            return None
        md = (mk.json().get("data") or {}).get("code") or {}
        id_ = (ik.json().get("data") or {}).get("code") or {}
        if not md.get("rank") and not id_.get("rank"):
            return None
        return {
            "market": md.get("rank"),
            "market_chg": md.get("rank_change"),
            "industry": id_.get("rank"),
            "industry_chg": id_.get("rank_change"),
        }
    except Exception as e:
        from finfeed.f10.utils.logger import vlog
        vlog(f"人气排名接口异常 ({code}): {e}")
        return None


def _fill_popular_rank(val, rank):
    if not rank:
        return val
    m = rank.get("market")
    i = rank.get("industry")
    if m is not None:
        val = re.sub(r'市场人气排名[：:]\s*',
                     f'市场人气排名：{m} ',
                     val, flags=re.I)
    if i is not None:
        val = re.sub(r'行业人气排名[：:]\s*',
                     f'行业人气排名：{i}', val)
    return val


def _is_note_row(row):
    if not row or len(row) == 0:
        return False
    first = str(row[0]).strip()
    return len(row) == 1 and (first.startswith("注") or first.startswith("说明") or first.startswith("（注"))


def _render_table(rows, max_width=None, colcap=40):
    """通用表格渲染。委托 ascii_table, 统一按终端宽度自适应与富余列分配。"""
    if not rows or len(rows) <= 1:
        return ""
    return ascii_table(rows, maxw=max_width, colcap=colcap, style="light")


def _render_latest_news(box):
    bd = box.find("div", class_="bd")
    if not bd:
        return ""
    items = []
    seen = set()
    for a in bd.find_all("a", href=True):
        text = a.get_text(strip=True)
        if not text or len(text) < 4:
            continue
        m = re.match(r'(\d{2}/\d{2}|\d{4}-\d{2}-\d{2})\s*(.*)', text)
        if m and m.group(2).strip():
            key = (m.group(1), m.group(2).strip()[:60])
            if key not in seen:
                seen.add(key)
                items.append((m.group(1), m.group(2).strip()))
    if not items:
        return ""
    items.sort(key=lambda x: x[0], reverse=True)
    rows = [["日期", "标题"]]
    for date, content in items:
        disp = content if wlen(content) <= 70 else content[:65] + "…"
        rows.append([date, disp])
    return ascii_table(rows, colcap=55)


def _render_theme_highlights(code, market_id):
    try:
        j = fuyao_get("concept/v1/theme_key_points",
                       {"subject": f"{market_id}-{code}"})
        pts = j.get("data") or []
        if not pts:
            return ""
        titles = [p.get("title", "") for p in pts[:6]]
        max_tw = max(wlen(t) for t in titles) if titles else 0
        lines = []
        for p in pts[:6]:
            t = p.get("title", "")
            date = p.get("update_date", "")
            content = re.sub(r"<[^>]+>", "", p.get("content", "") or "")
            content = _html.unescape(content).strip()
            lines.append(f"  {_pad(t, max_tw)}  ({date})")
            if content:
                for wl in _wrap_disp(content, _text_width()):
                    lines.append(f"  {wl}")
            lines.append("")
        return "\n".join(lines).strip()
    except Exception:
        return ""


_KV_NOISE = re.compile(
    r"查看明细>>|详情>>|了解更多>>|更多助力解读>>|点击进入>>|点击量[:：][^\s，,]*"
    r"|同行业排名第\s*\d+\s*位|重要股东质押.*$|质押股份占A股总股本比.*$"
    r"|板块波动提示.*$")
_INVALID_KV_LABEL = re.compile(r"^(单位|元|全部|收起|对比|指标名称|指标数据|所属地域|公司简介|说明|注)$")


def _split_cell_kv(cell_text):
    """把含多个『标签：值』的单元格切分成 (标签, 值) 列表。"""
    text = str(cell_text).strip()
    if not text:
        return []
    # 仅在标签起点处切分（标签前置 行首/空白/括号/逗号），避免把标签本身切碎
    starts = [0]
    for m in re.finditer(r"(?:^|[ \t\r\n（(，,；;])([^\s：:，,；;、。]+?)[：:]", text):
        starts.append(m.start(1))
    bounds = sorted(set(starts))
    out = []
    for idx, pos in enumerate(bounds):
        end = bounds[idx + 1] if idx + 1 < len(bounds) else len(text)
        seg = text[pos:end]
        m = re.match(r"^([^\s：:，,；;、。]+?)[：:]\s*(.*)$", seg)
        if not m:
            continue
        lbl = m.group(1).strip()
        if not lbl or _INVALID_KV_LABEL.match(lbl):
            continue
        val = _KV_NOISE.sub("", m.group(2))
        val = re.sub(re.escape(lbl) + r"\s*$", "", val)
        val = re.sub(r"\s*" + re.escape(lbl), "", val, count=1)
        val = re.sub(r"\s+", " ", val).strip()
        if lbl in ("市场人气排名", "行业人气排名") or val:
            out.append((lbl, val))
    return out


def _parse_company_summary(box):
    """公司概要：将页面文本框解析成干净的 (标签, 值) 列表。"""
    pairs = []
    tables = _extract_box_tables(box)
    for tbl in tables:
        for row in tbl:
            for cell in row:
                pairs += _split_cell_kv(cell)
    if not pairs:
        clone = BeautifulSoup(str(box), "html.parser")
        for tb in clone.find_all("table"):
            tb.extract()
        raw = clone.get_text(" ", strip=True)
        raw = _clean_chart_data(raw).strip()
        pairs += _parse_kv_raw(raw)
    seen, out = set(), []
    for lbl, val in pairs:
        if lbl not in seen:
            seen.add(lbl)
            out.append((lbl, val))
    return out


def _parse_kv_raw(raw):
    """兜底：从无表格的纯文本中解析『标签：值』对。"""
    pairs = []
    for seg in re.split(r"[ \t]{2,}", raw):
        seg = seg.strip()
        m = re.match(r"^([^：:]{1,18})[：:]\s*(.*)$", seg)
        if not m or not m.group(2).strip():
            continue
        label = m.group(1).strip()
        if _INVALID_KV_LABEL.match(label):
            continue
        val = _KV_NOISE.sub("", m.group(2))
        val = re.sub(re.escape(label) + r"\s*$", "", val)
        val = re.sub(r"\s*" + re.escape(label), "", val, count=1)
        val = re.sub(r"\s+", " ", val).strip()
        if label and val:
            pairs.append((label, val))
    seen, out = set(), []
    for lbl, v in pairs:
        if lbl not in seen:
            seen.add(lbl)
            out.append((lbl, v))
    return out


def render_latest(code, market_id):
    url = f"https://basic.10jqka.com.cn/{code}/"
    soup = _get_soup(url)
    if not soup:
        return f"{C.RED}请求失败{C.R}"
    _clean_soup(soup)

    tabular_titles = {"财务指标", "主力控盘", "大宗交易", "融资融券",
                       "公司概要", "近期重要事件", "龙虎榜"}

    sections = []
    seen_ids = set()
    for box in soup.find_all("div", class_=lambda c: c and "m_box" in c):
        if id(box) in seen_ids:
            continue
        parent_mbox = box.find_parent("div", class_=lambda c: c and "m_box" in c)
        if parent_mbox:
            seen_ids.add(id(box))
            continue
        seen_ids.add(id(box))

        flash_rows = _extract_flash_data(box)

        h = box.find(["h2", "h3"])
        title = h.get_text(strip=True) if h else ""
        if not title or len(title) > 30:
            continue

        if "新闻公告" in title:
            news_parts = []
            ssr_text = _render_latest_news(box)
            if ssr_text:
                news_parts.append(f"{section_header('公司公告', 'sub')}\n{ssr_text}")
            try:
                j = basicapi_get("notice/news", {"type": "stock", "code": code,
                                                  "current": 1, "limit": 15})
                hot_news = (j.get("data") or {}).get("data") or []
                if hot_news:
                    news_rows = [["日期", "来源", "标题"]]
                    for it in hot_news:
                        news_rows.append([
                            it.get("date", "") or _ts2date(it.get("time")),
                            it.get("source", ""),
                            _html.unescape(it.get("title", "")),
                        ])
                    api_table = ascii_table(news_rows, colcap=60)
                    if api_table:
                        news_parts.append(
                            f"{section_header('热点新闻', 'sub')}\n{api_table}")
            except Exception as e:
                from finfeed.f10.utils.logger import vlog
                vlog(f"热点新闻接口异常 ({code}): {e}")
            if news_parts:
                sections.append((title, "\n\n".join(news_parts)))
                continue

        if title == "公司概要":
            pairs = _parse_company_summary(box)
            if pairs:
                rank = _fetch_popular_rank(code)
                clean_pairs = []
                for lbl, _ in pairs:
                    val = ""
                    if lbl == "市场人气排名" and rank and rank.get("market") is not None:
                        val = str(rank["market"])
                    elif lbl == "行业人气排名" and rank and rank.get("industry") is not None:
                        val = str(rank["industry"])
                    else:
                        # 与当前标签同值同一单元格内的相邻字段已由 _split_cell_kv 拆开，
                        # 这里仅对剩余文本内的重复标签做清理
                        raw_val = dict(pairs).get(lbl, "")
                        val = re.sub(r'\s+', ' ', raw_val).strip()
                    if val:
                        clean_pairs.append((lbl, val))
                seen = set()
                deduped = []
                for lbl, val in clean_pairs:
                    if lbl in seen:
                        continue
                    seen.add(lbl)
                    deduped.append((lbl, val))
                clean_pairs = deduped
                tw = _text_width()
                # 键列宽取最长键(封顶 22)；超宽键截断补齐，保证值列上下对齐
                kw = min(max(wlen(k) for k, _ in clean_pairs), 22) if clean_pairs else 12
                vw = tw - kw - 4
                plain_lines = []
                for lbl, val in clean_pairs:
                    segs = _wrap_disp(val, vw) or [""]
                    first = True
                    for seg in segs:
                        key_part = _pad(_clip(lbl, kw), kw) if first else " " * kw
                        plain_lines.append(f"  {key_part}  {seg}")
                        first = False
                rendered = "\n".join(plain_lines)
                if rendered:
                    rendered_parts = [rendered]
                    if flash_rows and len(flash_rows) > 1:
                        trend_table = ascii_table(flash_rows, colcap=18)
                        if trend_table:
                            rendered_parts.append(
                                section_header("财务指标趋势", style="sub"))
                            rendered_parts.append(trend_table)
                    sections.append(
                        (title, "\n".join(rendered_parts)))
                    continue

        if title in tabular_titles:
            tables = _extract_box_tables(box)
            has_content = bool(tables or flash_rows)
            if has_content:
                rendered_parts = []
                for tbl in tables:
                    if len(tbl) <= 1:
                        continue
                    if "龙虎榜" in title:
                        for row in tbl:
                            if len(row) >= 1:
                                row[0] = re.sub(r'营业部.+', '营业部', row[0])
                    for row in tbl:
                        for ci in range(len(row)):
                            row[ci] = _trim_cell_text(row[ci])
                    if title in ("财务指标", "主力控盘", "龙虎榜"):
                        r = ascii_table(tbl, colcap=18)
                    else:
                        r = _render_table(tbl)
                    if r:
                        rendered_parts.append(r)
                for table in box.find_all("table"):
                    table.extract()
                extra = box.get_text(" ", strip=True)
                if extra:
                    extra = _clean_chart_data(extra).strip()
                    if extra.startswith(title):
                        extra = extra[len(title):].strip()
                    extra = re.sub(r'您对此栏目.*?(?:提建议|没用\d+)\s*', '', extra)
                    extra = re.sub(r'X\s*\S+\s*十大流通股东.*?(?:估算|元)', '', extra)
                    extra = re.sub(r'问财百科[：:].*$', '', extra)
                    extra = re.sub(r'A股PK.*$', '', extra)
                    extra = re.sub(r'以上为.*?(?:条件|成分股)', '', extra)
                    extra = re.sub(r'提示[：:].*?(?:成反比|上涨|下跌|集中)', '', extra)
                    extra = re.sub(r'\d{4}-\d{2}-\d{2}\s*', '', extra)
                    extra = re.sub(r'历史龙虎榜信息>>?\s*', '', extra)
                    extra = re.sub(r'更多[个回]股?解读>>?\s*', '', extra)
                    extra = re.sub(r'更多回测数据跟踪>>?\s*', '', extra)
                    extra = re.sub(r'机构成功率回测:.*$', '', extra)
                    extra = re.sub(r'\s+', ' ', extra).strip()
                    if len(extra) > 500:
                        extra = extra[:500] + "…"
                if extra and extra not in (r.strip() for r in rendered_parts):
                    extra_lines = []
                    for seg in extra.split("\n"):
                        seg = seg.strip()
                        if not seg:
                            continue
                        for wl in _wrap_disp(seg, _text_width()):
                            extra_lines.append(f"  {wl}")
                    if extra_lines:
                        rendered_parts.append("\n".join(extra_lines))
                if flash_rows and len(flash_rows) > 1:
                    trend_table = ascii_table(flash_rows, colcap=18)
                    if trend_table:
                        rendered_parts.append(
                            section_header("财务指标趋势", style="sub"))
                        rendered_parts.append(trend_table)
                if rendered_parts:
                    sections.append((title, "\n".join(rendered_parts)))
                    continue

        raw_text = _extract_mbox_paragraphs(box)
        if not raw_text or len(raw_text) < 3:
            raw_text = box.get_text(" ", strip=True)
            if not raw_text or len(raw_text) < 3:
                continue
            if len(raw_text) < 30:
                if "题材要点" in title:
                    api_text = _render_theme_highlights(code, market_id)
                    if api_text:
                        sections.append((title, api_text))
                        continue
                sections.append((title, raw_text))
                continue
            cleaned = _clean_chart_data(raw_text)
            if cleaned:
                raw_text = cleaned
        if len(raw_text) > 3000:
            raw_text = raw_text[:3000] + "…"
        sections.append((title, _norm_rendered_text(raw_text)))

    if not sections:
        return f"{C.RED}该股票暂无最新动态数据 (页面结构可能已变化){C.R}"

    SECTION_ORDER = ["公司概要", "财务指标", "主力控盘", "龙虎榜",
                     "大宗交易", "融资融券", "题材要点", "近期重要事件",
                     "新闻公告"]
    order_map = {name: i for i, name in enumerate(SECTION_ORDER)}
    sections.sort(key=lambda s: order_map.get(s[0], 999))

    # 输出阶段只做三件事：
    #   1) 已由 ascii_table 排版好的表格块 → 整体透传（绝不二次折行/合并，
    #      否则边框断裂、单元格错位）；
    #   2) 空行保留；
    #   3) 其余行原样输出，仅当超出可用宽度时才折行。
    # 不再做 _norm_rendered_text 合并：它会把 KV 行/表格行并成一行再重排，
    # 是此前"表格线断裂、缩进错位"的主要根源。
    _TBL_TOP = "┌┏╔"
    _TBL_BOT = "└┗╚"
    tw = _text_width()

    out = []
    for title, text in sections:
        if text.startswith(title):
            text = text[len(title):].strip()

        out.append(section_header(title))

        lines = text.split("\n")
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if stripped and stripped[0] in _TBL_TOP:
                while i < len(lines):
                    out.append(lines[i])
                    s2 = lines[i].strip()
                    if s2 and s2[0] in _TBL_BOT:
                        i += 1
                        break
                    i += 1
                continue
            if not stripped:
                out.append("")
                i += 1
                continue
            if wlen(stripped) > tw:
                for wl in _wrap_disp(stripped, tw):
                    out.append(wl)
            else:
                out.append(lines[i])
            i += 1
        out.append("")

    return "\n".join(out)


_extract_falsh_data = _extract_flash_data
