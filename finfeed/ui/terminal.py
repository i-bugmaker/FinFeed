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
from rich.layout import Layout

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


def _sentiment_icon(sentiment: str) -> Text:
    """情绪图标"""
    if sentiment == "positive":
        return Text("▲", style="green")
    elif sentiment == "negative":
        return Text("▼", style="red")
    else:
        return Text("─", style="dim")


def build_news_table(news_list: list[NewsItem], max_rows: int = 0) -> Table:
    """构建新闻表格"""
    table = Table(
        box=box.SIMPLE_HEAVY,
        border_style="blue",
        show_header=True,
        header_style="bold bright_white on blue",
        show_lines=False,
        pad_edge=False,
        expand=True,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", width=3, justify="right", no_wrap=True)
    table.add_column("情绪", width=3, no_wrap=True)
    table.add_column("标题", overflow="ellipsis", no_wrap=True, ratio=1)
    table.add_column("来源", width=9, no_wrap=True)
    table.add_column("时间", style="dim", width=17, no_wrap=True)

    shown = 0
    for idx, n in enumerate(news_list):
        if max_rows and shown >= max_rows:
            break

        title = n.title
        url = n.url or "#"
        source = n.source

        source_color = get_source_color(source)

        title_display = Text()
        if url and url != "#":
            title_display.append(title, style=Style(link=url))
        else:
            title_display.append(title)

        source_tag = Text(source, style=source_color)

        table.add_row(
            str(idx + 1),
            _sentiment_icon(n.sentiment),
            title_display,
            source_tag,
            n.publish_time,
        )
        shown += 1

    return table


def build_header(
    cycle: int,
    total_news: int,
    new_count: int,
    interval: int,
    status: str,
    web_port: int,
) -> Panel:
    """构建顶部信息栏"""
    now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")

    if "补抓" in status or "离线" in status:
        status_style = "yellow"
        status_icon = "⏳"
    elif "新增" in status or new_count > 0:
        status_style = "green"
        status_icon = "✓"
    elif "无新" in status:
        status_style = "dim"
        status_icon = "○"
    elif "抓取" in status or "运行" in status:
        status_style = "cyan"
        status_icon = "●"
    else:
        status_style = "bright_white"
        status_icon = "○"

    left = Text.assemble(
        ("⚡", "bold yellow"),
        (" FinFeed", "bold bright_white"),
        (" 实时监控", "bright_cyan"),
    )
    center = Text.assemble(
        (f"第 {cycle} 轮" if cycle > 0 else "准备中", "magenta"),
        (" │ ", "dim"),
        ("库内 ", "dim"),
        (f"{total_news:,}", "bold bright_white"),
        (" 条", "dim"),
        (" │ ", "dim"),
        ("+", "dim"),
        (f"{new_count}", "bold green" if new_count > 0 else "dim"),
        (" 条新", "dim"),
        (" │ ", "dim"),
        (f"间隔 {interval}s", "dim"),
        (" │ ", "dim"),
        (f"{status_icon} ", status_style),
        (status, status_style),
    )
    right = Text(now_str, style="bright_cyan")

    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(justify="left", ratio=1)
    grid.add_column(justify="center", ratio=2)
    grid.add_column(justify="right", ratio=1)
    grid.add_row(left, center, right)

    return Panel(
        grid,
        border_style="bright_blue",
        box=box.DOUBLE_EDGE,
        padding=(0, 1),
    )


def build_footer(web_port: int, source_stats: dict[str, int]) -> Panel:
    """构建底部状态栏"""
    parts = []
    parts.append(("按 Ctrl+C 退出", "dim"))
    parts.append((" │ ", "dim"))
    parts.append(("Web: ", "dim"))
    parts.append((f"http://localhost:{web_port}", Style(color="bright_cyan", link=f"http://localhost:{web_port}")))

    if source_stats:
        parts.append((" │ ", "dim"))
        source_items = list(source_stats.items())[:8]
        for i, (name, cnt) in enumerate(source_items):
            if i > 0:
                parts.append((" ", "dim"))
            dname = get_display_name(name)
            parts.append((f"{dname}", get_source_color(name)))

    return Panel(
        Align.center(Text.assemble(*parts)),
        border_style="dim",
        box=box.SIMPLE,
        padding=(0, 1),
    )


class TerminalUI:
    """终端 TUI 实时监控界面（无闪烁优化版）"""

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
        self._first_render = True

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
        """渲染完整界面"""
        news_list, source_stats = _filter_forum_content(self._news_list, self._source_stats)

        header = build_header(
            cycle=self._cycle,
            total_news=self._total_news,
            new_count=self._new_count,
            interval=self._interval,
            status=self._status,
            web_port=self._web_port,
        )

        term_height = console.size.height
        max_rows = max(8, term_height - 8)
        table = build_news_table(news_list, max_rows=max_rows)

        footer = build_footer(self._web_port, source_stats)

        return Group(header, table, footer)

    async def run(self):
        """启动 TUI 主循环（alternate screen 防闪烁）"""
        self._running = True
        self._update_event.clear()

        try:
            with Live(
                self._render(),
                console=console,
                screen=True,
                refresh_per_second=2,
                transient=False,
                vertical_overflow="ellipsis",
            ) as self._live:
                while self._running:
                    try:
                        await asyncio.wait_for(self._update_event.wait(), timeout=10.0)
                        if self._running:
                            self._live.update(self._render(), refresh=True)
                        self._update_event.clear()
                    except asyncio.TimeoutError:
                        if self._running:
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
    parts = [
        Align.center(Text("✅ FinFeed 单次抓取完成", style="bold white on blue")),
        Align.center(Text.assemble(
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
            (f" │ 离线补抓 {catch_up_cycles} 轮" if catch_up_cycles > 0 else "", "yellow"),
        )),
    ]
    console.print(Panel(
        Group(*parts),
        border_style="bright_blue",
        box=box.DOUBLE_EDGE,
        padding=(1, 2),
    ))
    console.print()
    table = build_news_table(news_list)
    console.print(table)
