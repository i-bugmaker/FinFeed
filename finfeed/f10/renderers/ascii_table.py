import re
import shutil

from finfeed.f10.renderers.terminal import C
from finfeed.f10.utils.cjk import _clip, _pad, _wrap_disp, wlen
from finfeed.f10.utils.text import (
    _STOCK_CODE_CELL,
    _STOCK_NAME_CELL,
    _drop_noise_cols,
    _protect_stock_codes,
)

_MAX_TERM = 134  # 表格/框架宽度上限（随终端自动适配的“天花板”）
_TERM_BASE = 100

# 由 CLI --width 设置的宽度覆盖（None 表示跟随终端）
_width_override = None


def set_term_width(w):
    """CLI --width 覆盖：同时放宽 _MAX_TERM 天花板。"""
    global _width_override, _MAX_TERM
    w = max(62, int(w))
    _width_override = w
    _MAX_TERM = max(_MAX_TERM, w)


def _term_width(default=_TERM_BASE):
    """整体宽度（含边框），随终端宽度自动适配，封顶 _MAX_TERM。"""
    if _width_override:
        return _width_override
    try:
        w = shutil.get_terminal_size((default, 24)).columns
    except Exception:
        w = default
    return max(62, min(w, _MAX_TERM))


def _text_width():
    """正文可用宽度（扣去左右边距），供长文本折行使用。"""
    return max(56, min(_term_width() - 4, _MAX_TERM - 4))


_BORDER_STYLES = {
    "light": {
        "h": "─", "v": "│",
        "tl": "┌", "tr": "┐", "bl": "└", "br": "┘",
        "lt": "├", "rt": "┤", "tt": "┬", "bt": "┴",
        "cross": "┼",
        "h_head": "─", "h_mid": "─",
    },
    "heavy": {
        "h": "━", "v": "┃",
        "tl": "┏", "tr": "┓", "bl": "┗", "br": "┛",
        "lt": "┣", "rt": "┫", "tt": "┳", "bt": "┻",
        "cross": "╋",
        "h_head": "━", "h_mid": "━",
    },
    "double": {
        "h": "═", "v": "║",
        "tl": "╔", "tr": "╗", "bl": "╚", "br": "╝",
        "lt": "╠", "rt": "╣", "tt": "╦", "bt": "╩",
        "cross": "╬",
        "h_head": "═", "h_mid": "═",
    },
    "simple": {
        "h": "-", "v": "|",
        "tl": "+", "tr": "+", "bl": "+", "br": "+",
        "lt": "+", "rt": "+", "tt": "+", "bt": "+",
        "cross": "+",
        "h_head": "-", "h_mid": "-",
    },
}


def _is_numeric_col(rows, col_idx):
    if col_idx == 0 and len(rows) > 1:
        return False
    samples = [str(r[col_idx]).strip() for r in rows[1:] if str(r[col_idx]).strip()]
    if not samples:
        return False
    numeric_count = 0
    for s in samples:
        s_clean = s.replace("%", "").replace(",", "").replace("+", "").replace("-", "", 1)
        if re.match(r"^[0-9.]+(?:亿|万|千|百|十|元|股|万元|亿元|万股|亿元)?$", s_clean):
            numeric_count += 1
        elif s_clean and s_clean.replace(".", "", 1).isdigit():
            numeric_count += 1
    return numeric_count / len(samples) > 0.7


def ascii_table(rows, maxw=None, colcap=40, style="light"):
    """渲染 ASCII 风格的表格。

    自动检测数值列（右对齐）、股票代码列、股票名称列，
    智能分配列宽，支持 CJK 全角字符宽度计算。

    Args:
        rows: 二维列表，第一行为表头
        maxw: 表格最大宽度（字符数），默认根据终端宽度自动计算
        colcap: 单列最大宽度限制
        style: 边框样式，可选 "light", "heavy", "double", "simple"

    Returns:
        渲染好的表格字符串，包含换行符

    Example:
        >>> data = [["名称", "代码", "价格"], ["贵州茅台", "600519", "1800.50"]]
        >>> print(ascii_table(data))
    """
    rows = _drop_noise_cols(rows)
    if not rows or not rows[0]:
        return ""
    if maxw is None:
        maxw = _term_width()
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    # 数据行空单元格统一占位 "--"，避免"字段存在但为空"被误读为渲染遗漏
    rows = ([rows[0]]
            + [["--" if not str(c).strip() else c for c in r] for r in rows[1:]])

    for ri in range(1, len(rows)):
        rows[ri] = [_protect_stock_codes(c) for c in rows[ri]]

    _stock_code_cols = set()
    _stock_name_cols = set()
    for ci in range(ncol):
        hdr_txt = str(rows[0][ci]).strip()
        code_hits = sum(1 for r in rows[1:] if _STOCK_CODE_CELL.match(str(r[ci]).strip()))
        name_hits = sum(1 for r in rows[1:] if _STOCK_NAME_CELL.match(str(r[ci]).strip()))
        if code_hits > len(rows) * 0.3:
            _stock_code_cols.add(ci)
        elif (name_hits > len(rows) * 0.3
                # 表头须带"名称/简称/股东/股票"提示，否则"姓名""职务"这类
                # 纯短汉字列(如 董事/独立董事/总经理)会被误判为股票名称列，
                # 其 want-min_w 被当作 protected_need 提前扣光，挤掉日期等
                # 不可折列的正常宽度分配
                and any(k in hdr_txt for k in ("名称", "简称", "股东", "股票"))):
            _stock_name_cols.add(ci)

    _numeric_cols = set()
    for ci in range(ncol):
        if ci not in _stock_code_cols and ci not in _stock_name_cols and _is_numeric_col(rows, ci):
            _numeric_cols.add(ci)

    # 日期型列（内容含 YYYY-MM-DD）：折行会切断起止日期，破坏可读性。
    # 这类列不属于"长文本可折行列"，必须在宽度分配时优先拿满自身内容宽度。
    _date_cols = set()
    for ci in range(ncol):
        if any(re.search(r"\d{4}-\d{2}-\d{2}", str(r[ci])) for r in rows[1:]):
            _date_cols.add(ci)

    want = [min(max(wlen(str(rows[0][i])),
                    max((wlen(str(r[i])) for r in rows[1:]),
                        default=0)),
                 colcap)
            for i in range(ncol)]
    want = [max(w, 2) for w in want]
    hdr_w = [min(wlen(str(rows[0][i])), colcap) for i in range(ncol)]

    budget = maxw - (3 * ncol + 1)
    protected = set(_stock_code_cols) | set(_stock_name_cols)

    # 优先保证表头完整显示；极端放不下时才退化等比分配
    if sum(hdr_w) <= budget:
        min_w = [max(hdr_w[i], min(want[i], 10)) for i in range(ncol)]
        cw = list(min_w)
        # 保护列(股票代码/名称)最后会加宽到自身内容宽度: 必须预先从富余中
        # 扣除这部分, 否则分配完成后再补齐会把总宽顶破 maxw, 表格在终端里
        # 被硬折行(边框断裂/右侧线消失/单元格内容甩到行首)
        protected_need = sum(max(0, want[ci] - min_w[ci]) for ci in protected)
        remain = budget - sum(cw) - protected_need
        # 极端情况下保护列需求超过预算: remain 为负会让所有短列/日期列
        # 分配失效(add<=0), 这里钳制到 0, 让 protected 列最后补齐并由安全阀兜底
        if remain < 0:
            remain = 0
        # 富余分配: 先满足短列(日期/来源/数字等非长文本列)自身内容需要,
        # 再让长文本列吃满剩余空间. 避免长列独占导致只需+2的短列被折行.
        text_priority = [i for i in range(ncol)
                         if want[i] >= 12 and i not in _numeric_cols
                         and i not in protected and i not in _date_cols]
        short = [i for i in range(ncol)
                 if want[i] > cw[i] and i not in text_priority and i not in protected]
        short.sort(key=lambda i: 0 if i in _date_cols else 1)  # 日期列优先拿满宽度
        for i in short:
            add = min(want[i] - cw[i], remain)
            if add > 0:
                cw[i] += add
                remain -= add
                if remain <= 0:
                    break
        for i in text_priority:
            # 单正文列时不吃 colcap 束缚, 直接吃满剩余宽度(如"日期+内容"的窄表应撑满整行)
            upper = colcap if len(text_priority) > 1 else (cw[i] + remain + 1)
            add = min(upper - cw[i], remain)
            if add > 0:
                cw[i] += add
                remain -= add
            if remain <= 0:
                break
        for ci in protected:
            cw[ci] = max(cw[ci], want[ci])
        # 安全阀: 任何情况下总宽不得超过 maxw, 否则终端会硬折行毁掉表格
        while sum(cw) > budget:
            m = max(range(ncol), key=lambda i: cw[i])
            floor_m = max(hdr_w[m], 4)
            if cw[m] <= floor_m:
                break
            cw[m] -= 1
    else:
        total = sum(want)
        # 极窄终端退化：给长文本列保留最小可读宽度 6，
        # 削减时也只在 6 以上削，避免"一行一个字"式断行
        cw = [max(6, int(w * budget / total)) for w in want] if total else want[:]
        cw = [min(w, max(want[i], 6)) for i, w in enumerate(cw)]
        for ci in protected:
            cw[ci] = max(cw[ci], want[ci])
        while sum(cw) > budget and max(cw) > 6:
            m = cw.index(max(cw))
            if cw[m] - 1 < 6 and max(cw) <= 6:
                break
            cw[m] -= 1

    bs = _BORDER_STYLES.get(style, _BORDER_STYLES["light"])

    def fmt(cells):
        wrapped = [_wrap_disp(cells[i], cw[i]) or [""] for i in range(ncol)]
        height = max(len(w) for w in wrapped)
        lines = []
        for li in range(height):
            parts = []
            for i in range(ncol):
                seg = wrapped[i][li] if li < len(wrapped[i]) else ""
                if i in _numeric_cols:
                    parts.append(_pad(seg, cw[i], align="r"))
                else:
                    parts.append(_pad(seg, cw[i]))
            lines.append(f"{bs['v']} " + f" {bs['v']} ".join(parts) + f" {bs['v']}")
        return "\n".join(lines)

    top = bs["tl"] + bs["tt"].join(bs["h"] * (w + 2) for w in cw) + bs["tr"]
    head_sep = bs["lt"] + bs["cross"].join(bs["h_head"] * (w + 2) for w in cw) + bs["rt"]
    bot = bs["bl"] + bs["bt"].join(bs["h"] * (w + 2) for w in cw) + bs["br"]
    header = fmt(rows[0])
    out = [f"{C.DIM}{top}{C.R}", f"{C.B}{C.BCYN}{header}{C.R}", f"{C.DIM}{head_sep}{C.R}"]
    for ri, r in enumerate(rows[1:]):
        out.append(fmt(r))
    out.append(f"{C.DIM}{bot}{C.R}")
    return "\n".join(out)


def kv_table(pairs, maxw=None):
    """渲染键值对表格。

    左侧显示键（高亮），右侧显示值，支持自动换行。
    每 5 行显示一条分隔线。

    Args:
        pairs: 键值对列表 [(key, value), ...]
        maxw: 最大宽度，默认根据终端宽度自动计算（上限 100）

    Returns:
        渲染好的键值对表格字符串

    Example:
        >>> pairs = [["公司名称", "贵州茅台酒股份有限公司"], ["股票代码", "600519"]]
        >>> print(kv_table(pairs))
    """
    if not pairs:
        return ""
    if maxw is None:
        maxw = _text_width()
    kw = min(max(wlen(k) for k, _ in pairs), 18)
    vw = maxw - kw - 7
    out = []
    for idx, (k, v) in enumerate(pairs):
        segs = _wrap_disp(v, vw) or [""]
        for i, seg in enumerate(segs):
            key = _pad(_clip(k, kw), kw) if i == 0 else " " * kw
            tint = (f"{C.B}{C.BCYN}{key}{C.R}") if i == 0 else key
            out.append(f"  {tint}  {seg}")
        if (idx + 1) % 5 == 0 and idx < len(pairs) - 1:
            sep_w = min(kw + vw + 4, 60)
            out.append(f"  {C.DIM}{'┄' * sep_w}{C.R}")
    return "\n".join(out)


def kv_table_grouped(groups):
    """渲染分组的键值对表格。

    多个分组之间用点线分隔，每组内部使用 kv_table 渲染。

    Args:
        groups: 分组列表 [(group_name, pairs), ...]，pairs 为键值对列表

    Returns:
        渲染好的分组键值对表格字符串

    Example:
        >>> groups = [
        ...     ("基本信息", [["公司名称", "贵州茅台"], ["代码", "600519"]]),
        ...     ("财务数据", [["净利润", "500亿"]]),
        ... ]
        >>> print(kv_table_grouped(groups))
    """
    parts = []
    for gname, pairs in groups:
        if not pairs:
            continue
        block = kv_table(pairs)
        if gname:
            block = f"{section_header(gname, style='sub', level=3)}\n{block}"
        parts.append(block)
    return ("\n" + divider("dot") + "\n").join(parts)


def section_header(title, style="default", level=2):
    """生成章节标题。

    支持多种样式和级别，用于不同层级的内容分隔。

    Args:
        title: 标题文本
        style: 样式，可选 "default", "accent", "sub"
        level: 标题级别，1-4，级别 1 为大标题（带边框），级别 2-4 为行内标题

    Returns:
        带颜色和样式的标题字符串

    Example:
        >>> print(section_header("公司资料"))
        >>> print(section_header("高管介绍", style="sub", level=3))
    """
    if level == 1:
        w = _term_width()
        bar = "━" * (w - 4)
        pad_l = max(0, (w - wlen(title) - 6) // 2)
        pad_r = max(0, w - pad_l - wlen(title) - 6)
        return f"\n  {C.B}{C.BMAG}┏{bar}┓{C.R}\n  {C.B}{C.BMAG}┃{C.R} {' ' * pad_l}{C.B}{C.WHT}{title}{C.R}{' ' * pad_r} {C.B}{C.BMAG}┃{C.R}\n  {C.B}{C.BMAG}┗{bar}┛{C.R}"
    elif level == 2:
        icon, color = "▸", C.BCYN
    elif level == 3:
        icon, color = "●", C.CYN
    elif level == 4:
        icon, color = "·", C.DIM
    else:
        icon, color = "▸", C.BCYN
    if style == "accent":
        icon, color = "◆", C.BMAG
    elif style == "sub":
        icon, color = "●", C.CYN
    return f"{C.B}{color}{icon} {title}{C.R}"


def divider(style="thin", width=None):
    """生成分割线。

    Args:
        style: 分割线样式，可选 "thin"（细实线）、"dot"（点线）、"thick"（粗实线）
        width: 分割线宽度，默认根据终端宽度自动计算（上限 100）

    Returns:
        带颜色的分割线字符串

    Example:
        >>> print(divider("dot"))
        >>> print(divider("thin", width=60))
    """
    w = (width or _term_width()) - 2  # 扣除左右 2 空格缩进，使整行宽度等于框架宽度
    chars = {"thin": "─", "dot": "┄", "thick": "═"}
    ch = chars.get(style, "─")
    return f"  {C.DIM}{ch * w}{C.R}"
