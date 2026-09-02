"""
用户界面模块
===========

提供 Web 界面和终端输出功能。

子模块:
    - web_fastapi: FastAPI 后端与 Web 共享运行时（web_fastapi.shared）
    - terminal: 终端输出格式化
"""

from .terminal import TerminalUI, build_display, build_news_table, console, print_once_result

__all__ = ["TerminalUI", "build_display", "build_news_table", "console", "print_once_result"]
