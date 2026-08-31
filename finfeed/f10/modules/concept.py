import html as _html
import re

from finfeed.f10 import ths_config
from finfeed.f10.http_client import _get_soup, _ths_api, api_failed
from finfeed.f10.renderers.ascii_table import _text_width, ascii_table, section_header
from finfeed.f10.renderers.terminal import C
from finfeed.f10.utils.cjk import _wrap_disp, wlen
from finfeed.f10.utils.logger import vlog


def fuyao_get(path, params):
    return _ths_api("fuyao/f10_stock_index", path, params)


def fuyao_info_get(path, params):
    return _ths_api("fuyao/info", path, params)


def _fmt_stock(stk, detail=False):
    name = stk.get("name", "")
    chg = stk.get("price_change_ratio_pct", "")
    board = stk.get("stock_boards_for_days", "")
    tail = ""
    if detail:
        cp = stk.get("close_price")
        wt = stk.get("weight")
        parts = []
        if cp not in (None, ""):
            parts.append(f"{cp}元")
        if wt not in (None, ""):
            parts.append(f"权重{wt}")
        if parts:
            tail = " [" + " ".join(parts) + "]"
    if board and board not in ("首板", "—", "-", ""):
        core = f"{C.GRN}{name}({chg}% {board}){C.R}" if chg else f"{C.GRN}{name}{C.R}"
    else:
        core = f"{C.GRN}{name}({chg}%){C.R}" if chg else f"{C.GRN}{name}{C.R}"
    return core + tail


def _render_concept_ssr(code):
    url = f"https://basic.10jqka.com.cn/{code}/concept.html"
    soup = _get_soup(url)
    if not soup:
        return ""
    out = []
    for h in soup.find_all(["h2", "h3"]):
        title = re.sub(r"\s+", "", h.get_text(strip=True))
        if not title or len(title) > 24:
            continue
        if not any(k in title for k in ("概念热点", "个股概念", "概念")):
            continue
        tbs = []
        for sib in h.find_all_next():
            if sib.name in ("h2", "h3"):
                break
            if sib.name == "table":
                tbs.append(sib)
        if not tbs:
            continue
        rows = []
        for tb in tbs[:2]:
            for tr in tb.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
        if len(rows) <= 1:
            continue
        deduped = [rows[0]]
        for r_idx in range(1, len(rows)):
            if rows[r_idx] != rows[r_idx - 1]:
                deduped.append(rows[r_idx])
        rows = deduped
        out.append(section_header(f"{title} (SSR 兜底)"))
        out.append(ascii_table(rows, colcap=30))
        out.append("")
    if out:
        out.append(f"{C.DIM}(注: 数据来自 SSR 兜底, 非实时 API){C.R}")
    return "\n".join(out)


def _render_emerging_concepts(code):
    """从概念页解析「新兴概念」(tag="新兴概念-XXX") 作为 SSR 补充。

    常规概念优先走 stock_concept_list API；新兴概念在该 API 中未单独分层，
    但概念页的 gnStockList 单元格按 tag 属性区分「常规概念/新兴概念」，
    此处仅补充新兴概念，避免与 API 结果重复。
    """
    url = f"https://basic.10jqka.com.cn/{code}/concept.html"
    soup = _get_soup(url)
    if not soup:
        return ""
    items = []
    for td in soup.find_all("td", class_="gnStockList"):
        tag = (td.get("tag") or "").strip()
        if not tag.startswith("新兴概念"):
            continue
        row = td.find_parent("tr")
        cells = [x.get_text(" ", strip=True) for x in row.find_all("td")]
        if len(cells) < 3:
            continue
        name = cells[1].strip()
        desc = re.sub(r"\s*(查看更多|展开|收起)[…...]?\s*$", "", cells[2]).strip()
        if name:
            items.append((name, desc))
    if not items:
        return ""
    out = [section_header(f"新兴概念 (SSR 补充 {len(items)} 个)")]
    tw = _text_width()
    for name, desc in items:
        out.append(section_header(name, "sub"))
        if desc:
            for seg in _wrap_disp(desc, tw):
                out.append(f"    {seg}")
        else:
            out.append(f"    {C.DIM}--{C.R}")
    out.append("")
    return "\n".join(out)


def render_concept(code, market_id):
    out = []
    api_ok = False
    j = fuyao_get("concept/v1/stock_concept_list",
                  {"market_id": market_id, "code": code})
    if api_failed(j):
        vlog(f"概念列表 API 失败 ({code})，将尝试 SSR 兜底")
    data = j.get("data") or []
    if data:
        api_ok = True
        total = len(data)
        names = "、".join(c.get("name", "") for c in data)
        out.append(section_header(f"所属概念 ({total} 个)"))
        tw = _text_width()
        out.append("  " + "\n  ".join(_wrap_disp(names, tw)))
        out.append("")

        show_n = min(total, ths_config.DISPLAY_LIMIT)
        if total > show_n:
            out.append(f"  {C.DIM}(共 {total} 个概念，概念详解仅展示前 {show_n} 个，"
                       f"--limit 可调整){C.R}")
        for c in data[:show_n]:
            cname = c.get("name", "")
            ex = (c.get("explain") or "").strip()
            leading = c.get("leading") or []
            components = c.get("components") or []
            subs = c.get("sub_concepts") or []
            out.append(section_header(cname, "sub"))

            meta = []
            chg = c.get("price_change_ratio_pct")
            if chg not in (None, ""):
                meta.append(f"板块涨跌 {chg}%")
            if (c.get("rise_cnt") not in (None, "")
                    and c.get("fall_cnt") not in (None, "")):
                meta.append(f"涨/跌家 {c.get('rise_cnt')}/{c.get('fall_cnt')}")
            if c.get("quote_code"):
                meta.append(f"指数 {c.get('quote_code')}")
            if c.get("has_etf") and c.get("etf_code"):
                meta.append(f"关联ETF {c.get('etf_code')}")
            if c.get("fit_rank") not in (None, ""):
                meta.append(f"相关度排名 {c.get('fit_rank')}")
            if components:
                meta.append(f"成份 {len(components)} 只")
            if meta:
                out.append("    " + "  ".join(meta))
            tags = c.get("tags") or []
            if tags:
                out.append("    " + f"{C.DIM}标签:{C.R} " + "、".join(tags))

            if ex:
                for seg in _wrap_disp(ex, tw):
                    out.append(f"    {seg}")
            if leading:
                out.append("    龙头: " + _fmt_stock(leading[0], detail=True))
                for s in leading[1:3]:
                    out.append("         " + _fmt_stock(s, detail=True))
            if subs:
                out.append(f"    {C.DIM}子概念:{C.R}")
                for sc in subs:
                    sname = sc.get("name", "")
                    stks = sc.get("stocks") or []
                    if stks:
                        names = "、".join(sk.get("stockName", "") for sk in stks)
                        head = f"      · {sname} ("
                        ind = " " * wlen(head)
                        wrapped = _wrap_disp(names, tw - len(head) - 1)
                        out.append(head + wrapped[0] + ")")
                        for seg in wrapped[1:]:
                            out.append(ind + seg + ")")
                    else:
                        out.append(f"      · {sname}")
        out.append("")

    j = fuyao_get("concept/v1/theme_key_points", {"subject": f"{market_id}-{code}"})
    pts = j.get("data") or []
    if pts:
        api_ok = True
        out.append(section_header(f"题材要点 ({len(pts)} 条)"))
        tw = _text_width()
        for p in pts:
            title = p.get("title", "")
            date = p.get("update_date", "")
            content = re.sub(r"<[^>]+>", "", p.get("content", "") or "")
            content = _html.unescape(content).strip()
            out.append(f"  {C.YEL}{title}{C.R}  {C.DIM}{date}{C.R}")
            for seg in _wrap_disp(content, tw):
                out.append(f"    {seg}")
            out.append("")

    for strategy in ("2", "1", "3"):
        j = fuyao_get("concept/v1/share_upward_cycle",
                      {"market_id": market_id, "code": code, "strategy": strategy})
        raw = j.get("data")
        cyc = []
        if isinstance(raw, dict):
            cyc = raw.get("list") or raw.get("data") or []
        elif isinstance(raw, list):
            cyc = raw
        if cyc:
            break
    if cyc:
        api_ok = True
        out.append(section_header("股价上行周期归因"))
        tw = _text_width()
        for seg in cyc[:4]:
            rng = f"{seg.get('from','')}~{seg.get('to','')}"
            raw_incr = seg.get("range_incr_ratio") or seg.get("range_incr_sum") or ""
            try:
                incr = f"{float(raw_incr):.2f}"
            except (ValueError, TypeError):
                incr = str(raw_incr)
            reason = re.sub(r"<[^>]+>", "", seg.get("range_reason", "") or "")
            reason = _html.unescape(reason).strip()
            meta = []
            days = seg.get("trade_day_num", "")
            if days:
                meta.append(f"{days}个交易日")
            inflow = seg.get("range_main_capital_net_inflow")
            if inflow not in (None, ""):
                try:
                    meta.append(f"主力净流入 {float(inflow) / 1e8:.2f}亿")
                except Exception:
                    meta.append(f"主力净流入 {inflow}")
            turn = seg.get("range_turnover_ratio")
            if turn not in (None, ""):
                meta.append(f"换手率 {turn}%")
            concepts = seg.get("related_concept") or []
            if concepts:
                meta.append("关联 " + " ".join(concepts[:3]))
            out.append(f"  {C.MAG}[{rng}] 区间涨幅 {incr}%{C.R}")
            if meta:
                for line in _wrap_disp("  ".join(meta), tw - 4):
                    out.append(f"    {C.DIM}{line}{C.R}")
            for line in _wrap_disp(reason, tw):
                out.append(f"    {line}")
            out.append("")

    if not api_ok:
        ssr_text = _render_concept_ssr(code)
        if ssr_text:
            return ssr_text
    emerging = _render_emerging_concepts(code)
    if emerging:
        out.append(emerging)

    if not out:
        return f"{C.RED}未取到概念题材数据 (接口可能调整){C.R}"
    return "\n".join(out)
