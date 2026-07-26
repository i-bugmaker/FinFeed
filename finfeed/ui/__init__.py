"""
用户界面模块
===========

提供 Web 界面和终端输出功能。

子模块:
    - web: Web 服务器和 HTML 模板
    - terminal: 终端输出格式化
"""

from .web.server import start_web_server
from .terminal import print_once_result, console, build_news_table, TerminalUI