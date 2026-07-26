#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""终端 UI 模块（基于 Rich）"""

import asyncio
from typing import Optional, List, Dict

from rich import box
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.console import Console, Group
from rich.align import Align
from rich.style import Style

from finfeed.config.settings import (
    get_source_color, get_display_name, DEFAULT_WEB_PORT,
)
from finfeed.config.sources import get_forum_source_names
from finfeed.utils.time_utils import now_bj
from finfeed.storage.models import NewsItem

_FORUM_SOURCE_NAMES = get_forum_source_names()


def _filter_forum_content(news_list: list[NewsItem], source_stats: dict[str, int]) -> tuple[list[NewsItem], dict[str, int]]:
    """过滤掉舆情相关的新闻和统计数据，仅保留财经新闻"""
    filtered_news = [n for n in news_list if n.source not in _FORUM_SOURCE_NAMES]
    filtered_stats = {name: cnt for name, cnt in source_stats.items() if name not in _FORUM_SOURCE_NAMES}
    return filtered_news, filtered_stats


console = Console()


def build_news_table(news_list: list[NewsItem], max_rows: int = 0) -> Table:
    """构建新闻表格"""
    table = Table(
        box=box.ROUNDED,
        border_style="bright_blue",
        show_header=True,
        header_style="bold bright_cyan",
        show_lines=False,
        pad_edge=True,
        expand=True,
    )
    table.add_column("序号", style="dim", width=4, justify="right", no_wrap=True)
    table.add_column("标题 (Ctrl+点击跳转)", overflow="ellipsis", no_wrap=True, ratio=1)
    table.add_column("来源", style="", width=12, no_wrap=True)
    table.add_column("时间", style="dim", width=19, no_wrap=True)

    shown = 0
    for idx, n in enumerate(news_list):
        if max_rows and shown >= max_rows:
            break
        pub_time = n.publish_time
        source = n.source
        title = n.title
        url = n.url or "#"

        source_color = get_source_color(source)

        title_display = Text()
        if url and url != "#":
            title_display.append(title, style=Style(link=url))
            title_display.append(" ", style=Style())
        else:
            title_display.append(title)

        source_tag = Text(f"[{source}]", style=source_color)

        table.add_row(
            str(idx + 1),
            title_display,
            source_tag,
            pub_time,
        )
        shown += 1

    return table


def build_display(
    news_list: list[NewsItem],
    cycle: int,
    total_news: int,
    new_count: int,
    source_stats: dict[str, int],
    interval: int,
    status: str,
    web_port: int = DEFAULT_WEB_PORT,
) -> Group:
    """构建完整的终端布局"""
    now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")

    news_list, source_stats = _filter_forum_content(news_list, source_stats)

    if "补抓" in status or "离线" in status:
        status_style = "yellow"
    elif "新增" in status:
        status_style = "green"
    elif "无新" in status:
        status_style = "dim"
    elif "抓取" in status or "运行" in status:
        status_style = "cyan"
    else:
        status_style = "bright_white"

    header_panel = Panel(
        Group(
            Align.center(
                Text.assemble(
                    ("⚡ FinFeed 实时监控", "bold bright_white"),
                    ("  │  ", "dim"),
                    (now_str, "bright_cyan"),
                )
            ),
            Align.center(
                Text.assemble(
                    (f"第 {cycle} 轮" if cycle > 0 else "准备中", "magenta"),
                    ("  │  ", "dim"),
                    ("库内 ", "dim"),
                    (f"{total_news}", "bold bright_white"),
                    (" 条", "dim"),
                    (f"  │  +{new_count} 条新", "bold green" if new_count > 0 else "dim"),
                    ("  │  ", "dim"),
                    (f"间隔 {interval}s", "dim"),
                    ("  │  ", "dim"),
                    (status, status_style),
                )
            ),
        ),
        border_style="bright_blue",
        box=box.DOUBLE_EDGE,
        padding=(0, 2),
    )

    term_height = console.size.height
    max_rows = max(10, term_height - 15)
    table = build_news_table(news_list, max_rows=max_rows)

    footer_panel = Panel(
        Align.center(
            Text.assemble(
                ("按 Ctrl+C 退出", "dim"),
                ("  │  ", "dim"),
                ("网页仪表盘: ", "dim"),
                (f"http://localhost:{web_port}", Style(color="bright_cyan", link=f"http://localhost:{web_port}", underline=False)),
            )
        ),
        border_style="dim",
        box=box.SIMPLE,
        padding=(0, 1),
    )

    return Group(header_panel, table, footer_panel)


class TerminalUI:
    """终端 TUI 实时监控界面"""

    def __init__(self, interval: int, web_port: int = DEFAULT_WEB_PORT):
        self._interval = interval
        self._web_port = web_port
        self._news_list: List[NewsItem] = []
        self._source_stats: Dict[str, int] = {}
        self._cycle = 0
        self._total_news = 0
        self._new_count = 0
        self._status = "准备中"
        self._live: Optional[Live] = None
        self._update_event = asyncio.Event()
        self._running = False
        self._last_size = (0, 0)

    def update_data(
        self,
        news_list: List[NewsItem],
        cycle: int,
        total_news: int,
        new_count: int,
        source_stats: Dict[str, int],
        status: str,
    ):
        """更新显示数据"""
        self._news_list = news_list
        self._cycle = cycle
        self._total_news = total_news
        self._new_count = new_count
        self._source_stats = source_stats
        self._status = status
        self._update_event.set()

    def _render(self) -> Group:
        """渲染当前状态"""
        return build_display(
            news_list=self._news_list,
            cycle=self._cycle,
            total_news=self._total_news,
            new_count=self._new_count,
            source_stats=self._source_stats,
            interval=self._interval,
            status=self._status,
            web_port=self._web_port,
        )

    def _size_changed(self) -> bool:
        """检测终端窗口尺寸是否变化"""
        current = (console.size.width, console.size.height)
        if current != self._last_size:
            self._last_size = current
            return True
        return False

    async def run(self):
        """启动 TUI 主循环（alternate screen 防闪烁）"""
        self._running = True
        self._update_event.clear()
        self._last_size = (console.size.width, console.size.height)

        try:
            with Live(
                self._render(),
                console=console,
                screen=True,
                refresh_per_second=4,
                transient=False,
                vertical_overflow="ellipsis",
            ) as self._live:
                while self._running:
                    try:
                        await asyncio.wait_for(self._update_event.wait(), timeout=0.5)
                        if self._running:
                            self._live.update(self._render(), refresh=True)
                        self._update_event.clear()
                    except asyncio.TimeoutError:
                        if self._running and self._size_changed():
                            self._live.update(self._render(), refresh=True)
        except Exception:
            pass
        finally:
            console.show_cursor(True)

    def stop(self):
        """停止 TUI"""
        self._running = False
        self._update_event.set()
        if self._live:
            self._live.stop()
            self._live = None


def print_once_result(news_list: list[NewsItem], total_inserted: int, total_in_db: int, catch_up_cycles: int = 0):
    """单次模式打印结果"""
    news_list, _ = _filter_forum_content(news_list, {})
    console.print()
    catch_up_str = f" │ [yellow]离线补抓 {catch_up_cycles} 轮[/]" if catch_up_cycles > 0 else ""
    console.print(Panel(
        Group(
            Align.center(
                Text.assemble(
                    ("✅ FinFeed 单次抓取完成", "bold white on blue"),
                )
            ),
            Align.center(
                Text.assemble(
                    (now_bj().strftime('%Y-%m-%d %H:%M:%S'), "cyan"),
                    (" │ ", "dim"),
                    ("抓取(财经新闻) ", "dim"),
                    (f"{len(news_list)}", "bold bright_white"),
                    (" 条 │ ", "dim"),
                    ("新增入库 ", "dim"),
                    (f"{total_inserted}", "bold green"),
                    (" 条 │ ", "dim"),
                    ("库内共 ", "dim"),
                    (f"{total_in_db}", "bold bright_white"),
                    (" 条", "dim"),
                    (catch_up_str, ""),
                )
            ),
        ),
        border_style="bright_blue",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    ))
    console.print()
    table = build_news_table(news_list)
    console.print(table)
