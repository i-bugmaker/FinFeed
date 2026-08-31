"""模块包：14 个 F10 模块的抓取与渲染。

包级 re-export 仅供 engine.py 使用（`from finfeed.f10.modules import ...`）；
其余符号请直接从子模块导入（如 `from finfeed.f10.modules.news import basicapi_get`）。
"""

from finfeed.f10.modules.company import (
                       _fetch_company_soup,
                       render_company_detail,
                       render_execs,
                       render_ipo_history,
                       render_ipo_info,
)
from finfeed.f10.modules.concept import render_concept
from finfeed.f10.modules.finance import render_finance
from finfeed.f10.modules.holder import render_holder_count
from finfeed.f10.modules.latest import render_latest
from finfeed.f10.modules.news import render_news
from finfeed.f10.modules.operate import render_main_compose
from finfeed.f10.modules.position import render_position

__all__ = [
    "render_latest", "render_concept", "render_news", "render_position",
    "render_finance", "render_main_compose", "render_company_detail",
    "render_execs", "render_ipo_info", "render_ipo_history",
    "_fetch_company_soup", "render_holder_count",
]
