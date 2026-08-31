import html as _html
import sys

from finfeed.f10 import ths_config
from finfeed.f10.http_client import _get_soup, api_failed
from finfeed.f10.modules.news import basicapi_get
from finfeed.f10.parsers.ssr import render_sections
from finfeed.f10.renderers.ascii_table import _text_width, ascii_table, kv_table, section_header
from finfeed.f10.renderers.terminal import C
from finfeed.f10.utils.cjk import _wrap_disp
from finfeed.f10.utils.text import _norm_rendered_text


def render_position(code, market_id):
    out = []
    api_ok = False
    api_err = False
    api_sections = set()

    tab = basicapi_get("holder/stock/org_holder/tab",
                       {"code": code, "year": 0, "limit": 5})
    if api_failed(tab):
        api_err = True
    periods = tab.get("data") or []
    report_date = ""
    if periods:
        report_date = periods[0].get("report", "")
        srows = [["报告期", "机构数占比", "持股户数", "持股市值", "环比增减"]]
        rate = basicapi_get("holder/stock/org_holder/rate",
                            {"code": code, "limit": 6, "year": 0})
        for p in (rate.get("data") or [])[:6]:
            hn = p.get("total_holder", "")
            try:
                hn = f"{float(hn)/1e4:.2f}万"
            except Exception:
                pass
            mv = p.get("total_market_value", "")
            try:
                mv = f"{float(mv)/1e8:.2f}亿"
            except Exception:
                pass
            chg = p.get("total_holder_change_rate", "")
            try:
                chg = f"{float(chg)*100:.2f}%"
            except Exception:
                pass
            srows.append([p.get("date", ""),
                          f'{p.get("total_rate", "")}%（{p.get("org_num", "")}家）',
                          str(hn), str(mv), str(chg)])
        if len(srows) > 1:
            out.append(section_header("机构持股汇总 (API)"))
            out.append(ascii_table(srows))
            out.append("")
            api_ok = True
            api_sections.add("机构持股汇总")

    if periods:
        latest = periods[0]
        trows = [["机构类别", "持股占比%", "持股数"]]
        for tl in (latest.get("tab_list") or []):
            th = tl.get("holder_num", "")
            try:
                th = f"{float(th)/1e4:.2f}万"
            except Exception:
                pass
            trows.append([tl.get("name", ""), tl.get("rate", ""), str(th)])
        if len(trows) > 1:
            out.append(section_header(
                f"机构类别持股占比 ({latest.get('date','')})"))
            out.append(ascii_table(trows))
            out.append("")
            api_ok = True
            api_sections.add("机构类别持股占比")

    if report_date:
        j = basicapi_get("holder/stock/org_holder/detail",
                         {"code": code, "date": report_date,
                          "page": 1, "size": ths_config.DISPLAY_LIMIT, "type": "all"})
        if api_failed(j):
            api_err = True
        data = (j.get("data") or {})
        rows_data = data.get("data") or []
        if rows_data:
            total_n = data.get("total") or len(rows_data)
            note = f"，共 {total_n} 名" if total_n and int(total_n) > len(rows_data) else ""
            out.append(section_header(f"机构持股明细 ({report_date} 前 {len(rows_data)} 名{note})"))
            rows = [["机构名称", "类型", "持股数", "持股市值", "占比%", "变动", "基金排名/标志"]]
            for it in rows_data:
                num = it.get("holder_num", "")
                mv = it.get("holder_market_value", "")
                try:
                    num = f"{float(num)/1e4:.2f}万"
                except Exception:
                    pass
                try:
                    mv = f"{float(mv)/1e8:.2f}亿"
                except Exception:
                    pass
                chg = it.get("change", "")
                if it.get("is_new"):
                    chg = "新进"
                mark = ""
                fr = it.get("fund_rank")
                if fr not in (None, ""):
                    mark = f"基金#{fr}"
                if it.get("is_jump"):
                    mark = (mark + " 新上榜" if mark else "新上榜")
                rows.append([_html.unescape(it.get("org_name", "")),
                             it.get("org_type_name", ""), str(num), str(mv),
                             it.get("rate", ""), str(chg), mark])
            out.append(ascii_table(rows, colcap=34))
            out.append("")
            api_ok = True
            api_sections.add("机构持股明细")

    try:
        url = f"https://basic.10jqka.com.cn/{code}/position.html"
        soup = _get_soup(url)
        if soup:
            blocks = render_sections(soup, allow=["机构持股", "举牌", "被举牌", "IPO获配"])
            for title, items in blocks:
                if api_ok and any(s in title for s in api_sections):
                    continue
                out.append(section_header(title))
                for kind, payload in items:
                    if kind == "table":
                        out.append(ascii_table(payload))
                    elif kind == "kv":
                        out.append(kv_table(payload))
                    else:
                        out.append(
                            "  " + "\n  ".join(_wrap_disp(_norm_rendered_text(payload), _text_width())))
                    out.append("")
                if not api_ok:
                    api_ok = True
    except Exception as e:
        print(f"{C.DIM}[异常] position SSR: {e}{C.R}", file=sys.stderr)

    if not out:
        if api_err:
            return f"{C.RED}主力持仓接口请求失败 (非空数据，稍后重试或加 --verbose){C.R}"
        return f"{C.RED}未取到主力持仓数据 (接口可能调整){C.R}"
    return "\n".join(out)
