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
from rich.align import Align
from rich.style import Style

from config.settings import (
    get_source_color, get_display_name, DEFAULT_WEB_PORT,
)
from utils.time_utils import now_bj
from storage.models import NewsItem

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
    table: Optional[Table] = None,
) -> Group:
    """构建完整的终端布局"""
    now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")

    merged_stats: dict[str, int] = {}
    for name, count in source_stats.items():
        dname = get_display_name(name)
        merged_stats[dname] = merged_stats.get(dname, 0) + count

    if "补抓" in status or "离线" in status:
        status_style = "yellow"
    elif "新增" in status:
        status_style = "green"
    elif "无新" in status:
        status_style = "dim"
    elif "抓取" in status:
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

    if table is None:
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
                ("  │  ", "dim"),
                ("数据来源: ", "dim"),
                *[(f"{name}({cnt})  ", get_source_color(name)) for name, cnt in source_stats.items()],
            )
        ),
        border_style="dim",
        box=box.SIMPLE,
        padding=(0, 1),
    )

    return Group(header_panel, table, footer_panel)


def print_once_result(news_list: list[NewsItem], total_inserted: int, total_in_db: int, catch_up_cycles: int = 0):
    """单次模式打印结果"""
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
                    ("抓取 ", "dim"),
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
