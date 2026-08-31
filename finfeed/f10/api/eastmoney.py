import re
import time

from finfeed.f10.http_client import safe_get
from finfeed.f10.ths_config import _INVALID_KEYWORDS, _INVALID_PREFIXES, _VALID_CODE_PREFIXES
from finfeed.f10.utils.logger import vlog

# 东财 suggest 接口中 A 股的行类型：
#   AStock = 沪深主板/创业板；23 = 科创板(688xxx 笔记中 Classify 非 AStock)
_A_SHARE_CLASSIFIES = ("AStock", "23")

# suggest 接口的唯一定义处：URL / token / Referer 只在此出现，
# 全项目的搜索（Web 建议、完整性对账）统一走 suggest_rows。
_SUGGEST_URL = "https://searchadapter.eastmoney.com/api/suggest/get"
_SUGGEST_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
_SUGGEST_REFERER = "https://www.eastmoney.com/"


def market_id_from_code(code, sec_type_name=""):
    """根据股票代码和证券类型推断市场 ID。

    市场 ID 用于同花顺 F10 接口的参数：
    - 17: 沪市（上海证券交易所）
    - 33: 深市（深圳证券交易所）
    - 151: 北交所（北京证券交易所）

    Args:
        code: 6 位股票代码
        sec_type_name: 证券类型名称（如 "沪A"、"深A"、"北交所"），可选

    Returns:
        str: 市场 ID 字符串（"17"、"33" 或 "151"）

    Example:
        >>> market_id_from_code("600519")
        '17'
        >>> market_id_from_code("000001")
        '33'
        >>> market_id_from_code("834765", "北交所A股")
        '151'
    """
    if "北" in sec_type_name or "京" in sec_type_name:
        return "151"
    if "沪" in sec_type_name:
        return "17"
    if "深" in sec_type_name:
        return "33"
    if code.startswith(("60", "68", "9", "11", "5")):
        return "17"
    if code.startswith(("8", "4", "92")):
        return "151"
    return "33"


def _is_valid_ashare(code, name):
    if not code or len(code) != 6 or not code.isdigit():
        return False
    if not name:
        return False
    name = name.strip().replace(' ', '')
    for p in _INVALID_PREFIXES:
        if name.startswith(p.replace(' ', '')):
            return False
    if 'PT' in name.upper() or '退市' in name:
        return False
    for kw in _INVALID_KEYWORDS:
        if kw in name:
            return False
    return any(code.startswith(p) for p in _VALID_CODE_PREFIXES)


def _normalize_suggest_name(name):
    """清洗东财 suggest 返回的股票名称临时标记。

    新股前几日常带 C/N 前缀(如 "C宇树-W")，特别表决权/未盈利股带 -W/-U 后缀，
    去掉后便于终端展示与后续查询。
    """
    if not name:
        return name
    n = re.sub(r"^[CNU]\s*", "", name.strip())
    n = re.sub(r"-[WU]$", "", n)
    return n.strip()


def suggest_rows(keyword, count=8, timeout=15,
                 min_delay=None, max_delay=None, _retries=3):
    """查询东财 suggest 接口，返回已过滤的 A 股候选行（未做任何交互）。

    全项目唯一的搜索来源：URL、token、A 股过滤规则均只在此定义一次。
    调用方可按需覆盖限速/超时参数。

    Args:
        keyword: 股票名称或 6 位代码
        count: 期望返回条数
        timeout: 单次请求超时秒数
        min_delay / max_delay: 请求前随机延迟区间，None 表示沿用全局配置
        _retries: 失败重试次数

    Returns:
        list[dict]: 原始候选行；无结果或请求失败时为空列表
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []
    params = {
        "input": keyword,
        "type": "14",
        "token": _SUGGEST_TOKEN,
        "count": str(count),
        "_": str(int(time.time() * 1000)),
    }
    try:
        r = safe_get(_SUGGEST_URL, params=params,
                     headers={"Referer": _SUGGEST_REFERER},
                     timeout=timeout, min_delay=min_delay,
                     max_delay=max_delay, _retries=_retries)
        rows = (r.json().get("QuotationCodeTable") or {}).get("Data") or []
    except Exception as e:
        vlog(f"suggest 查询失败: {keyword}: {e}")
        return []
    return [x for x in rows
            if x.get("Classify") in _A_SHARE_CLASSIFIES
            and _is_valid_ashare(x.get("Code", ""), x.get("Name", ""))]
