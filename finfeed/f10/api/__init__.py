"""东方财富数据接口包。

统一从 api.eastmoney 导入；包级 re-export 保持命名空间契约。
"""

from finfeed.f10.api.eastmoney import (
                           _is_valid_ashare,
                           _normalize_suggest_name,
                           market_id_from_code,
                           suggest_rows,
)

__all__ = ["suggest_rows", "market_id_from_code",
           "_is_valid_ashare", "_normalize_suggest_name"]
