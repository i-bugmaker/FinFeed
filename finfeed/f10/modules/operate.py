from finfeed.f10.http_client import _get_soup, safe_get
from finfeed.f10.parsers.ssr import _is_loading_placeholder, render_sections
from finfeed.f10.renderers.ascii_table import _text_width, ascii_table, section_header
from finfeed.f10.renderers.terminal import C
from finfeed.f10.ths_config import F10_REFERER
from finfeed.f10.utils.cjk import _wrap_disp


def _render_compose_ssr_fallback(code, market_id):
    url = f"https://basic.10jqka.com.cn/{code}/operate.html"
    soup = _get_soup(url)
    if not soup:
        return ""
    blocks = render_sections(soup, allow=["主营构成", "主营"])
    out = []
    for title, items in blocks:
        for kind, payload in items:
            if kind == "table":
                has_loading = any(
                    _is_loading_placeholder(c) for row in payload[1:]
                    for c in row if c
                )
                if has_loading:
                    continue
                out.append(section_header(f"{title} (SSR 兜底)"))
                out.append(ascii_table(payload))
                out.append("")
            elif kind == "text" and len(payload) > 20:
                out.append(section_header(f"{title} (SSR 兜底)"))
                out.append("  " + "\n  ".join(_wrap_disp(payload, _text_width())))
                out.append("")
    if out:
        out.append(f"{C.DIM}(注: API 暂不可用, 数据来自 SSR 兜底){C.R}")
    return "\n".join(out)


def render_main_compose(code, market_id, periods=1):
    url = ("https://basic.10jqka.com.cn/basicapi/operate/index/v1/product_index_query/"
           f"?code={code}&market={market_id}&type=stock&timeField=date"
           f"&analysisTypes=product,area,industry&sortIndex=income&currency=CNY"
           f"&account=1&yoy=1&level=1&child=1"
           f"&expands=product_introduction&locale=zh_CN")
    try:
        r = safe_get(url, headers={"Referer": F10_REFERER}, timeout=20)
        data = r.json()
    except Exception:
        data = {"status_code": -1}
    if not isinstance(data, dict) or data.get("status_code") != 0:
        return _render_compose_ssr_fallback(code, market_id)

    LABEL = {"area": "按地区", "product": "按产品", "industry": "按行业"}

    def _num(v, scale=1.0):
        try:
            return f"{float(v) / scale:.2f}"
        except (TypeError, ValueError):
            return ""

    def _pct(v):
        try:
            return f"{float(v) * 100:.2f}%"
        except (TypeError, ValueError):
            return ""

    out = []
    for rec in (data.get("data") or []):
        atype = rec.get("analysis_type", "")
        label = LABEL.get(atype, atype)
        times = rec.get("time_operate_index_item_list") or []
        if not times:
            continue
        for t in times[:max(1, periods)]:
            period = t.get("time", "")
            items = t.get("product_index_item_list") or []
            if not items:
                continue
            out.append(section_header(f"{label} · 报告期 {period}", "accent"))
            out.append(f"  {C.DIM}(单位: 万元; 占比/同比/毛利率为百分比){C.R}")
            rows = [["项目", "营收", "收入占比", "成本", "成本占比",
                     "毛利", "利润占比", "毛利率", "营收同比"]]
            for it in items:
                pname = (it.get("product_name") or "").strip() or "—"
                idx = {x.get("index_id"): x
                       for x in (it.get("index_analysis_list") or [])}
                inc = idx.get("income", {})
                cost = idx.get("cost", {})
                prof = idx.get("gross_profit", {})
                rate = idx.get("gross_profit_rate", {})
                rows.append([
                    pname,
                    _num(inc.get("index_value"), 1e4),
                    _pct(inc.get("account")),
                    _num(cost.get("index_value"), 1e4),
                    _pct(cost.get("account")),
                    _num(prof.get("index_value"), 1e4),
                    _pct(prof.get("account")),
                    _pct(rate.get("index_value")),
                    _pct(inc.get("yoy")),
                ])
            out.append(ascii_table(rows, colcap=18))
            out.append("")
    if not out:
        return ""
    return "\n".join(out)
