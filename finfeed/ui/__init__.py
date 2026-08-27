"""
用户界面模块
===========

提供 Web 界面和终端输出功能。

子模块:
    - web: Web 共享运行时（ui.web.shared）与 FastAPI 后端（ui.web_fastapi）
    - terminal: 终端输出格式化
"""

from .terminal import TerminalUI, build_display, build_news_table, console, print_once_result

__all__ = ["TerminalUI", "build_display", "build_news_table", "console", "print_once_result"]
