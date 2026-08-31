import json
import random
import traceback

from finfeed.f10.http_client import _get_soup, safe_get
from finfeed.f10.parsers.ssr import render_sections
from finfeed.f10.renderers.ascii_table import _text_width, ascii_table, kv_table, section_header
from finfeed.f10.renderers.terminal import C
from finfeed.f10.ths_config import _UA_POOL
from finfeed.f10.utils.cjk import _wrap_disp
from finfeed.f10.utils.text import _norm_rendered_text


def render_finance(code, market_id):
    out = []

    try:
        url = (f"https://basic.10jqka.com.cn/api/stock/finance/"
               f"{code}_main.json")
        ref = f"https://basic.10jqka.com.cn/{code}/finance.html"
        r = safe_get(url, headers={"Referer": ref,
                         "User-Agent": random.choice(_UA_POOL)},
                        timeout=15)
        if r.status_code == 200:
            body = r.json()
            fd_raw = body.get("flashData")
            if fd_raw:
                fd = json.loads(fd_raw) if isinstance(fd_raw, str) else fd_raw
                titles = fd.get("title") or []
                report = fd.get("report") or []
                if titles and report and len(report) > 1:
                    periods = report[0]
                    nper = min(10, len(periods))
                    rows = [["指标"] + [p[:10] for p in periods[:nper]]]
                    max_i = min(len(titles) - 1, len(report) - 1, 24)
                    for i in range(1, max_i + 1):
                        ti = titles[i]
                        name = (ti[0] if isinstance(ti, (list, tuple))
                                else str(ti))
                        unit = (ti[1] if isinstance(ti, (list, tuple))
                                and len(ti) > 1 else "")
                        label = f"{name}({unit})" if unit else name
                        vals = report[i] if i < len(report) else []
                        row = [label]
                        for j in range(nper):
                            row.append(str(vals[j]) if j < len(vals) else "")
                        rows.append(row)
                    if len(rows) > 1:
                        out.append(
                            section_header("财务指标 (主要)"))
                        out.append(ascii_table(rows, colcap=18))
                        out.append("")

                ff_raw = body.get("fieldflashData")
                if ff_raw:
                    ffd = json.loads(ff_raw) if isinstance(ff_raw, str) else ff_raw
                    ft = ffd.get("title") or []
                    fr = ffd.get("report") or []
                    if ft and fr and len(fr) > 1:
                        fperiods = fr[0]
                        nper2 = min(10, len(fperiods))
                        frows = [["指标"] + [p[:10] for p in fperiods[:nper2]]]
                        max_fi = min(len(ft) - 1, len(fr) - 1, 24)
                        for i in range(1, max_fi + 1):
                            ti = ft[i]
                            name = (ti[0] if isinstance(ti, (list, tuple))
                                    else str(ti))
                            unit = (ti[1] if isinstance(ti, (list, tuple))
                                    and len(ti) > 1 else "")
                            label = f"{name}({unit})" if unit else name
                            vals = fr[i] if i < len(fr) else []
                            row = [label]
                            for j in range(nper2):
                                row.append(str(vals[j])
                                           if j < len(vals) else "")
                            frows.append(row)
                        if len(frows) > 1:
                            out.append(
                                section_header("财务指标 (全部)"))
                            out.append(ascii_table(frows, colcap=18))
                            out.append("")
    except Exception as e:
        from finfeed.f10.utils.logger import vlog
        vlog(f"财务指标 API 异常 ({code}): {e}\n{traceback.format_exc()}")
        out.append(f"{C.DIM}(财务指标API异常: "
                   f"{traceback.format_exc()[:80]}){C.R}")

    try:
        url = f"https://basic.10jqka.com.cn/{code}/finance.html"
        soup = _get_soup(url)
        if soup:
            blocks = render_sections(
                soup, allow=["诊断", "资产负债", "指标变动", "利润",
                             "现金流", "杜邦"])
            for title, items in blocks:
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
    except Exception as e:
        from finfeed.f10.utils.logger import vlog
        vlog(f"财务诊断/指标变动 SSR 异常 ({code}): {e}")
        out.append(f"{C.DIM}(财务诊断/指标变动 SSR 抓取异常){C.R}")

    if not out:
        return f"{C.RED}未取到财务分析数据 (接口可能调整){C.R}"
    return "\n".join(out)
