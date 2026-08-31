"""文本处理工具函数。

包含 HTML 清洗、文本规范化、表格解析、股票代码保护等工具函数。
"""

import html as _html
import re


def _clean_soup(soup):
    """清理 BeautifulSoup 对象，移除脚本、样式等无用标签。

    Args:
        soup: BeautifulSoup 对象

    Returns:
        清理后的 BeautifulSoup 对象（原地修改）
    """
    for t in soup(["script", "style", "noscript"]):
        t.extract()
    return soup


def _norm_label(s):
    return re.sub(r"[\s\u3000]+", "", s)


def _clean_cell(s):
    s = _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*(新进|不变|退出)?\s*流通A股\s*点击查看$",
               lambda m: m.group(1) if m.group(1) else "流通A股", s)
    s = re.sub(r"\s*点击查看$", "", s)
    s = re.sub(r"\s*[×✕✖╳]\s*", "", s)
    return s.strip()


def _table_to_rows(tb):
    """将 HTML 表格元素解析为二维列表。

    自动清理单元格内容，移除尾部空列，
    处理"序号"列的自动编号填充。

    Args:
        tb: BeautifulSoup 的 <table> 元素

    Returns:
        二维列表，每行是一个单元格内容的列表
    """
    rows = []
    for tr in tb.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        row = [_clean_cell(c.get_text(" ", strip=True)) for c in cells]
        while row and not row[-1]:
            row.pop()
        if not any(row):
            continue
        rows.append(row)

    if len(rows) >= 2:
        first_col_header = rows[0][0] if rows[0] else ""
        if re.sub(r"[（(].*[）)]", "", first_col_header).strip() == "序号":
            for i in range(1, len(rows)):
                if rows[i] and len(rows[i]) > 0 and (not rows[i][0] or rows[i][0].strip() in ("-", "—", "--", "")):
                    rows[i][0] = str(i)

    result = []
    for row in rows:
        nonempty = [c for c in row if c]
        if len(nonempty) == 1:
            result.append([nonempty[0]])
        else:
            result.append(row)

    return result


def _drop_noise_cols(rows):
    if not rows:
        return rows
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    keep = []
    for ci in range(ncol):
        body = [r[ci] for r in rows][1:] or [rows[0][ci]]
        if all(not x for x in body):
            continue
        keep.append(ci)
    return [[r[ci] for ci in keep] for r in rows]


def _norm_rendered_text(text):
    """规范化渲染文本，清理多余空白和换行。

    处理规则:
    - 将非换行的空白字符压缩为单个空格
    - 移除行尾空白
    - 将 3 个以上连续换行压缩为 2 个（保留段落分隔）
    - 将单个换行替换为空格（合并段落内换行）

    Args:
        text: 输入文本

    Returns:
        规范化后的文本
    """
    if not text:
        return text
    text = re.sub(r'[^\S\n]+', ' ', text)
    text = re.sub(r'[ \t]+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    return text.strip()


_STOCK_CODE_RE = re.compile(r'(\d{6})\s+([\u4e00-\u9fff\w]+)')
_STOCK_CODE_CELL = re.compile(r'^\d{6}$')
_STOCK_NAME_CELL = re.compile(r'^[\u4e00-\u9fff]{2,6}\s?[A-Za-z]?\s?[A-Za-z]?$')


def _protect_stock_codes(text):
    if not text:
        return text
    return _STOCK_CODE_RE.sub(lambda m: m.group(1) + '\xa0' + m.group(2), str(text))
