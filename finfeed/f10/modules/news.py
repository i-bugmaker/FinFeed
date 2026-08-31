import html as _html
import json
import time

from finfeed.f10 import ths_config
from finfeed.f10.http_client import _get_soup, _ths_api, api_failed
from finfeed.f10.renderers.ascii_table import ascii_table, section_header
from finfeed.f10.renderers.terminal import C
from finfeed.f10.utils.logger import vlog


def basicapi_get(path, params):
    return _ths_api("basicapi", path, params)


def _render_research_reports(code):
    """从 news.html 内嵌的 #report_list_contents 解析券商研报列表。

    该数据以 JSON 数组形式藏在隐藏 div 中(display:none)，无需 JS 渲染即可读取。
    字段: thspj(评级)/title/source/researcher/date/url。
    """
    url = f"https://basic.10jqka.com.cn/{code}/news.html"
    soup = _get_soup(url)
    if not soup:
        return ""
    div = soup.find(id="report_list_contents")
    if not div:
        return ""
    try:
        data = json.loads(div.get_text("", strip=True))
    except (json.JSONDecodeError, TypeError) as e:
        vlog(f"研报列表 JSON 解析失败 ({code}): {e}")
        return ""
    if not isinstance(data, list) or not data:
        return ""
    show_n = min(ths_config.DISPLAY_LIMIT, len(data))
    truncated = len(data) > show_n
    out = [section_header(f"研报列表 (最近 {show_n} 条 / 共 {len(data)} 条)")]
    rows = [["评级", "标题", "机构", "研究员", "日期", "链接"]]
    for it in data[:show_n]:
        rating = (it.get("thspj") or "").strip()
        title = _html.unescape((it.get("title") or "").strip())
        source = (it.get("source") or "").strip()
        researcher = (it.get("researcher") or "").strip()
        date = (it.get("date") or "").strip()
        url = (it.get("url") or "").strip()
        rows.append([rating, title, source, researcher or "--", date, url])
    out.append(ascii_table(rows, colcap=52))
    if truncated:
        out.append(f"  {C.DIM}…另有 {len(data) - show_n} 条略去 "
                   f"(--limit 可调整显示条数){C.R}")
    return "\n".join(out)


def _ts2date(ts):
    try:
        return time.strftime("%Y-%m-%d", time.localtime(int(ts)))
    except Exception:
        return str(ts or "")


def render_news(code, market_id):
    out = []
    api_err = False
    j = basicapi_get("notice/pub", {"type": "stock", "limit": ths_config.DISPLAY_LIMIT,
                                    "page": 1, "code": code, "classify": "all",
                                    "market": market_id})
    if api_failed(j):
        api_err = True
    data = (j.get("data") or {})
    pub = data.get("data") or []
    if pub:
        total = data.get("total", len(pub))
        note = "，--limit 可调整" if total > len(pub) else ""
        out.append(section_header(f"公告列表 (最新 {len(pub)} 条 / 共 {total} 条{note})"))
        rows = [["日期", "类型", "标题"]]
        for it in pub:
            rows.append([_ts2date(it.get("time")),
                         str(it.get("type") or "--"),
                         _html.unescape(it.get("title", ""))])
        out.append(ascii_table(rows, colcap=70))
        out.append("")
    j = basicapi_get("notice/news", {"type": "stock", "code": code,
                                     "current": 1, "limit": ths_config.DISPLAY_LIMIT})
    if api_failed(j):
        api_err = True
    news = (j.get("data") or {}).get("data") or []
    if news:
        out.append(section_header(f"相关新闻 (最新 {len(news)} 条)"))
        rows = [["日期", "来源", "标题", "作者"]]
        for it in news:
            rows.append([it.get("date", "") or _ts2date(it.get("time")),
                         it.get("source", ""),
                         _html.unescape(it.get("title", "")),
                         it.get("author") or "--"])
        out.append(ascii_table(rows, colcap=60))
        out.append("")
    if not out:
        if api_err:
            return f"{C.RED}公告/新闻接口请求失败 (非空数据，稍后重试或查看 --verbose){C.R}"
        return f"{C.RED}未取到新闻公告数据 (接口可能调整){C.R}"
    reports = _render_research_reports(code)
    if reports:
        out.append("")
        out.append(reports)
    return "\n".join(out)
