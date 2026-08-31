import os
import re
import unicodedata
from typing import List, Union

# 歧义宽度字符（East Asian Ambiguous, 如 ★ ▼ … “” ─）的宽度处理。
# 默认按窄字符计（Windows Terminal/conhost 默认行为）；
# 终端按全角渲染这些字符时（如 mintty + CJK 字体），置 THS_AMBIGUOUS_WIDE=1
# 或调用 set_ambiguous_width(True)。
_amb_wide = os.environ.get("THS_AMBIGUOUS_WIDE", "") in ("1", "true", "True")


def set_ambiguous_width(wide):
    global _amb_wide
    _amb_wide = bool(wide)


def _cw(ch):
    """单字符显示宽度。"""
    ea = unicodedata.east_asian_width(ch)
    if ea in "WF":
        return 2
    if ea == "A" and _amb_wide:
        return 2
    return 1


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def wlen(s: Union[str, int, float]) -> int:
    """计算字符串的显示宽度（考虑 CJK 全角字符）。

    全角字符（中日韩文字、全角符号等）宽度计为 2，半角字符计为 1。
    ANSI 色码序列不计入宽度。

    Args:
        s: 输入字符串、数字或浮点数

    Returns:
        字符串的显示宽度（以半角字符为单位）

    Example:
        >>> wlen("hello")
        5
        >>> wlen("你好")
        4
        >>> wlen("hello你好")
        9
    """
    return sum(_cw(c) for c in _ANSI_RE.sub("", str(s)))


def _clip(s: Union[str, int, float], w: int) -> str:
    s = str(s)
    if wlen(s) <= w:
        return s
    out, cur = "", 0
    for c in s:
        cw = _cw(c)
        if cur + cw > w - 1:
            return out + "…"
        out += c
        cur += cw
    return out


def _pad(s: str, w: int, align: str = "l") -> str:
    d = w - wlen(s)
    if d <= 0:
        return s
    return s + " " * d if align == "l" else " " * d + s


_WRAP_BREAKS = "，、；;：: 　|/\t"


def _wrap_disp(s: Union[str, int, float], w: int) -> List[str]:
    s = str(s)
    if not s:
        return []
    # 单元格/文本中内嵌的换行先拆成多行，避免折行后残留控制字符破坏排版
    if "\n" in s or "\r" in s:
        out = []
        for part in s.replace("\r", "").split("\n"):
            out.extend(_wrap_disp(part, w))
        return out
    if "\t" in s:
        s = s.replace("\t", " ")
    if wlen(s) <= w:
        return [s]
    lines, cur, cw = [], "", 0
    for ch in s:
        c = _cw(ch)
        if cw + c > w:
            ba = -1
            for i in range(len(cur) - 1, -1, -1):
                if cur[i] in _WRAP_BREAKS:
                    ba = i
                    break
            if ba > 0:
                lines.append(cur[:ba + 1].rstrip())
                cur = cur[ba + 1:] + ch
                cw = wlen(cur)
                continue
            lines.append(cur)
            cur, cw = ch, c
        else:
            cur += ch
            cw += c
    if cur:
        lines.append(cur)
    return lines
