import re
import sys
from collections import Counter

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("缺少依赖: 请先运行  pip install requests beautifulsoup4")

from finfeed.f10.http_client import _get_soup
from finfeed.f10.renderers.ascii_table import (
    _text_width,
    ascii_table,
    divider,
    kv_table,
    section_header,
)
from finfeed.f10.renderers.terminal import C
from finfeed.f10.utils.cjk import _wrap_disp
from finfeed.f10.utils.logger import vlog
from finfeed.f10.utils.text import _clean_soup, _norm_rendered_text, _table_to_rows

_KV_LINE = re.compile(r"^(.{2,12}?)[:：]\s*(.+)$")
_NOISE_TITLE = re.compile(
    r"诊断|学习|意义|删除|方案|意见|动力|支持|换肤|登录|举报|纠错|声明|风险提示")
_PERSON_NAME = re.compile(r"^[\u4e00-\u9fa5]{2,4}$")


def _parse_kv(text):
    m = _KV_LINE.match(text.strip())
    if m:
        return re.sub(r"\s+", "", m.group(1)), m.group(2).strip()
    return None


def _is_loading_placeholder(text):
    s = re.sub(r"\s+", "", str(text or ""))
    return s in ("加载中...", "暂无数据", "暂无数据", "图表加载中", "加载中",
                 "charttit-nodata") or "charttit-nodata" in s[:40]


def _is_json_noise(text):
    """识别内嵌 flashData / JSON 明文（如财务诊断段），丢弃纯数据泄漏噪音。"""
    t = str(text or "").strip()
    if len(t) < 20:
        return False
    data_ratio = sum(1 for c in t if c in '[]{}",.0123456789:-') / len(t)
    if t[0] == "[" and data_ratio > 0.3:
        return True
    if t[0] == "{" and data_ratio > 0.3 and '"' in t[:8]:
        return True
    return False


def _p_to_clean_text(p):
    if not hasattr(p, "find_all"):
        return ""
    clone = BeautifulSoup(str(p), "html.parser")
    for a in clone.find_all("a", class_=re.compile(r"^(more|less)$")):
        a.decompose()
    for br in clone.find_all("br"):
        br.replace_with("\n")
    text = clone.get_text("\n", strip=True)
    text = re.sub(r"查看全部[▼]?", "", text)
    text = re.sub(r"收起[▲]?", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_section_text(h):
    candidates = []
    for sib in h.find_all_next():
        if sib.name in ("h2", "h3") and sib is not h:
            break
        if not hasattr(sib, "find_all"):
            continue
        for p in sib.find_all("p"):
            text = _p_to_clean_text(p)
            if not text or len(text) < 20:
                continue
            if _is_loading_placeholder(text):
                continue
            if _is_json_noise(text):
                continue
            candidates.append((len(text), text))

    if not candidates:
        for sib in h.find_all_next():
            if sib.name in ("h2", "h3") and sib is not h:
                break
            if sib.name == "div" and sib.get("class"):
                text = sib.get_text(separator=" ", strip=True)
                if not text or len(text) < 20:
                    continue
                if "免责声明" in text or "同花顺" in text[:20]:
                    continue
                if text.lstrip().startswith('[["') or text.lstrip().startswith('[['):
                    continue
                data_ratio = sum(1 for c in text if c in '[],".0123456789') / max(len(text), 1)
                if data_ratio > 0.5:
                    continue
                if "累计分红" in text[:40]:
                    continue
                candidates.append((len(text), text))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: -x[0])
    seen_prefixes = set()
    unique = []
    for _, text in candidates:
        prefix = re.sub(r"\s+", "", text)[:50]
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        unique.append(text)

    if not unique:
        return ""
    if len(unique) == 1 and len(unique[0]) > 3000:
        return _norm_rendered_text(unique[0][:3000] + "…")
    return _norm_rendered_text("\n\n".join(unique))


def render_sections(html_or_soup, max_rows=100, allow=None, max_tables=300):
    """解析 HTML/Soup 中的章节内容并结构化。

    遍历页面中的 h2/h3 标题，提取每个标题下的表格和文本内容，
    自动识别 KV 对、表格、纯文本三种格式。

    Args:
        html_or_soup: HTML 字符串或 BeautifulSoup 对象
        max_rows: 每个表格最多保留的行数（不含表头）
        allow: 白名单关键词列表，只保留标题包含这些关键词的章节
        max_tables: 每章节最多处理(渲染)的表格数量上限

    Returns:
        章节列表 [(title, [(kind, payload), ...]), ...]
        kind 可为 "kv"（键值对）、"table"（表格）、"text"（纯文本）

    Example:
        >>> html = "<h2>基本信息</h2><table>...</table>"
        >>> sections = render_sections(html, max_rows=20)
        >>> for title, items in sections:
        ...     print(title, len(items))
    """
    if isinstance(html_or_soup, BeautifulSoup):
        soup = html_or_soup
    else:
        soup = BeautifulSoup(html_or_soup, "html.parser")
    _clean_soup(soup)
    for t in soup.find_all(class_=True):
        cls = " ".join(t.get("class") or [])
        if re.search(r"\b(footer|page_bottom|copyright|m_feedback|vpop|votepop|"
                     r"guidebox|advert|ad_box|recommend_box)\b", cls):
            t.extract()
    for _id in ("footer", "page_bottom"):
        e = soup.find(id=_id)
        if e:
            e.extract()

    blocks, seen = [], set()
    for h in soup.find_all(["h2", "h3"]):
        title = re.sub(r"\s+", "", h.get_text(strip=True))
        if not title or len(title) > 24:
            continue
        whitelisted = bool(allow) and any(k in title for k in allow)
        if allow and not whitelisted:
            vlog(f"章节被 allow 白名单过滤: {title!r} "
                 f"(可用 --all-sections 查看)")
            continue
        if not whitelisted and (_NOISE_TITLE.search(title)
                                or _PERSON_NAME.match(title)):
            vlog(f"章节被噪音规则丢弃: {title!r}")
            continue
        tbs = []
        for sib in h.find_all_next():
            if sib.name in ("h2", "h3"):
                break
            if sib.name == "table":
                tbs.append(sib)
        rendered = []
        for tb in tbs[:max_tables]:
            if id(tb) in seen:
                continue
            seen.add(id(tb))
            for inner in tb.find_all("table"):
                inner.extract()
            rows = [r for r in _table_to_rows(tb) if any(c for c in r)]
            if not rows:
                continue
            if all(_is_loading_placeholder(c) for r in rows for c in r):
                continue
            lens = Counter(len(r) for r in rows)
            modal = lens.most_common(1)[0][0]

            # 单列表：KV / 纯文本。逐单元格收集 KV 对，不因行宽差异丢行，
            # 从而恢复「公告日期/交易金额/支付方式/交易方式」等多列行
            if modal == 1:
                cells = [c for r in rows for c in r if c]
                flat = [p for p in (_parse_kv(c) for c in cells) if p]
                if flat and len(flat) >= max(3, int(len(cells) * 0.5)):
                    rendered.append(("kv", flat))
                else:
                    txt = " ".join(cells)
                    if len(txt) > 4:
                        rendered.append(("text", txt))
                continue

            # 多列：只丢弃明显偏短的噪音行(合并标题/'注'声明等)，
            # 合法行统一补齐到最宽列数，不再按众数列长整行丢弃，
            # 从而保留关联交易多出的列、参股控股「被参股公司主营」列、退出前十大股东名单等
            rows = [r for r in rows if len(r) >= modal - 2]
            if not rows:
                continue
            ncol = max(len(r) for r in rows)
            norm = [r + [""] * (ncol - len(r)) for r in rows]

            flat, is_kv = [], True
            for r in norm:
                for cell in r:
                    if not cell:
                        continue
                    p = _parse_kv(cell)
                    if p:
                        flat.append(p)
                    else:
                        is_kv = False
                        break
                if not is_kv:
                    break
            if is_kv and len(flat) >= 3:
                rendered.append(("kv", flat))
            else:
                rendered.append(("table", norm[:max_rows + 1]))

        if not rendered:
            text_body = _extract_section_text(h)
            if text_body:
                rendered.append(("text", text_body))

        if rendered:
            blocks.append((title, rendered))
    return blocks


def fetch_legacy(code, module_file, allow=None, max_rows=None):
    """获取并渲染同花顺老版 F10 页面内容。

    从 basic.10jqka.com.cn 获取指定模块的 SSR 页面，
    解析并渲染为终端可显示的格式。

    Args:
        code: 6 位股票代码
        module_file: 模块文件名（如 "company.html", "holder.html"）
        allow: 白名单关键词列表，只保留标题包含这些关键词的章节
        max_rows: 每个表格最多保留的行数

    Returns:
        渲染好的文本字符串，包含表格、KV 对等

    Example:
        >>> text = fetch_legacy("600519", "company.html", max_rows=50)
        >>> print(text)
    """
    url = (f"https://basic.10jqka.com.cn/{code}/{module_file}"
           if module_file else f"https://basic.10jqka.com.cn/{code}/")
    soup = _get_soup(url)
    if soup is None:
        return f"{C.RED}请求失败或页面返回异常{C.R}"
    kwargs = {}
    if max_rows is not None:
        kwargs["max_rows"] = max_rows
    blocks = render_sections(soup, allow=allow, **kwargs)
    if not blocks:
        return f"{C.DIM}（该模块无可结构化展示的表格数据）{C.R}"
    tw = _text_width()
    sep = divider("thin")
    out = []
    for bi, (title, items) in enumerate(blocks):
        if bi > 0:
            out.append(sep)
        out.append(section_header(title))
        for kind, payload in items:
            if kind == "kv":
                out.append(kv_table(payload))
            elif kind == "table":
                out.append(ascii_table(payload))
            else:
                out.append("  " + "\n  ".join(_wrap_disp(_norm_rendered_text(payload), tw)))
            out.append("")
    return "\n".join(out).strip()
