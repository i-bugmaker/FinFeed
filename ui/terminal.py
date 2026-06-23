#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""终端 UI 模块（基于 Rich）"""

from typing import Optional

from rich import box
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.console import Console, Group

from config.settings import (
    get_source_color, get_display_name, DEFAULT_WEB_PORT,
)
from utils.time_utils import now_bj
from storage.models import NewsItem

console = Console()


def _make_link(url: str, text: str) -> str:
    """生成终端可点击的超链接（OSC 8 协议）"""
    if not url or url == "#":
        return text
    return f"\x1b]8;;{url}\x1b\\{text}\x1b]8;;\x1b\\"


def build_news_table(news_list: list[NewsItem], max_rows: int = 0) -> Table:
    """构建新闻表格"""
    total = len(news_list)
    table = Table(
        title=f"📰 财经资讯 ({total}条)",
        box=box.ROUNDED,
        border_style="cyan",
        show_header=True,
        header_style="bold white",
        show_lines=False,
        pad_edge=True,
        expand=True,
    )
    table.add_column("序号", style="yellow", width=4, justify="center", no_wrap=True)
    table.add_column("标题 (Ctrl+点击跳转)", style="cyan", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("来源", style="magenta", width=10, no_wrap=True)
    table.add_column("时间", style="dim", width=19, no_wrap=True)

    shown = 0
    for n in news_list:
        if max_rows and shown >= max_rows:
            break
        pub_time = n.publish_time
        source = n.source
        title = n.title
        url = n.url or "#"

        source_color = get_source_color(source)
        source_display = f"[{source_color}]{source}[/]"

        if url and url != "#":
            title_display = f"[link={url}]{title}[/link]"
        else:
            title_display = title

        table.add_row(str(shown + 1), title_display, source_display, pub_time)
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
    table: Optional[Table] = None,
) -> Group:
    """构建完整的终端布局"""
    now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")

    merged_stats: dict[str, int] = {}
    for name, count in source_stats.items():
        dname = get_display_name(name)
        merged_stats[dname] = merged_stats.get(dname, 0) + count

    stats_parts = []
    for name, count in merged_stats.items():
        if count > 0:
            stats_parts.append(f"{name}:{count}")
        else:
            stats_parts.append(f"[dim]{name}:0[/dim]")
    stats_line = " ".join(stats_parts)

    header_text = (
        f"[bold white] FinFeed 实时监控[/]"
        f" [dim]│[/] {now_str}"
        f" [dim]│[/] 第{cycle}轮"
        f" [dim]│[/] 库内{total_news}条"
        f"{' [green]│ +' + str(new_count) + '条新[/]' if new_count > 0 else ''}"
        f" [dim]│[/] 间隔{interval}s"
        f" [dim]│[/] {status}"
    )
    status_bar = Panel(
        Text.from_markup(header_text + "\n " + stats_line),
        border_style="cyan",
        box=box.SIMPLE,
    )

    if table is None:
        term_height = console.size.height
        max_rows = max(10, term_height - 12)
        table = build_news_table(news_list, max_rows=max_rows)

    footer = Panel(
        f"[dim]按 Ctrl+C 退出 │ 网页仪表盘: [cyan]http://localhost:{web_port}[/][/]",
        border_style="dim",
        box=box.SIMPLE,
    )

    return Group(status_bar, table, footer)


def print_once_result(news_list: list[NewsItem], total_inserted: int, total_in_db: int, catch_up_cycles: int = 0):
    """单次模式打印结果"""
    console.print()
    catch_up_str = f" | [yellow]离线补抓 {catch_up_cycles} 轮[/]" if catch_up_cycles > 0 else ""
    console.print(Panel(
        f"[bold white on blue] FinFeed 单次抓取完成 [/]"
        f" [cyan]{now_bj().strftime('%Y-%m-%d %H:%M:%S')}[/]"
        f" | 抓取 {len(news_list)} 条 | 新增入库 {total_inserted} 条 | 库内共 {total_in_db} 条"
        + catch_up_str,
        border_style="bright_blue",
    ))
    console.print()
    table = build_news_table(news_list)
    console.print(table)
