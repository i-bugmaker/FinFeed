#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""终端 UI 模块（基于 Rich）"""

import asyncio
import logging
from typing import Dict, List, Optional

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text

from finfeed.config.settings import (
    DEFAULT_WEB_PORT,
    get_source_color,
)
from finfeed.config.sources import get_flash_display_names
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

# 快讯类来源的展示名集合（7×24 实时短消息源）。
# TUI 终端仅展示快讯内容：文章类（长文/深度内容）与舆情论坛类一律过滤。
_FLASH_SOURCE_NAMES: set[str] = set(get_flash_display_names())


def _filter_flash_only(news_list: list[NewsItem], source_stats: dict[str, int]) -> tuple[list[NewsItem], dict[str, int]]:
    """仅保留快讯类内容，过滤掉文章类与舆情类新闻及其统计。

    条目过滤依据：NewsItem.category == 'flash'（与 cli.py 中
    db_get_recent_news(category='flash') 的查询口径一致）。不按来源名过滤，
    避免「格隆汇」这类快讯/文章共享展示名的来源被误保留文章内容。
    统计过滤依据：来源展示名 ∈ 快讯来源集合（见 config/flash_sources.py
    与 SOURCE_DISPLAY_NAMES 映射），仅展示快讯源的最近更新时间。
    """
    filtered_news = [n for n in news_list if n.category == 'flash']
    filtered_stats = {name: cnt for name, cnt in source_stats.items() if name in _FLASH_SOURCE_NAMES}
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
    restart_hotkey: bool = False,
) -> Layout:
    """构建完整的终端布局"""
    # 时间戳固定 19 字符（YYYY-MM-DD HH:MM:SS），宽度恒定避免 Align.center 在秒数跳变时重排；
    # 历史写法用裸 now_str()，秒位从 X→X+1 会引发 header 偶发横向 1px 抖动。
    now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    assert len(now_str) == 19, "时间戳格式必须固定 19 字符"

    news_list, source_stats = _filter_flash_only(news_list, source_stats)

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

    # 第二行同样做了字段宽度补齐：cycle(右对齐 6 字符)、total_news(右对齐 7)、new_count(右对齐 5)，
    # 防止 cycle 由 2 位 → 3 位（如 999 → 1000）时整行重新分栏。
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
                    (f"第 {cycle:>6d} 轮" if cycle > 0 else "   准备中", "magenta"),
                    ("  │  ", "dim"),
                    ("库内 ", "dim"),
                    (f"{total_news:>7d}", "bold bright_white"),
                    (" 条", "dim"),
                    (f"  │  +{new_count:>5d} 条新", "bold green" if new_count > 0 else "dim"),
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

    footer_parts = [("按 Ctrl+C 退出", "dim")]
    if restart_hotkey:
        footer_parts.append(("  │  ", "dim"))
        footer_parts.append(("按 Ctrl+R 重启", "dim"))
    footer_parts.extend(
        [
            ("  │  ", "dim"),
            ("网页仪表盘: ", "dim"),
            (
                f"http://localhost:{web_port}",
                Style(
                    color="bright_cyan",
                    link=f"http://localhost:{web_port}",
                    underline=False,
                ),
            ),
        ]
    )
    footer_text = Align.center(Text.assemble(*footer_parts))

    layout = Layout()
    layout.split_column(
        Layout(header_panel, name="header", size=4),
        Layout(name="body"),
        Layout(footer_text, name="footer", size=1),
    )

    term_height = console.size.height
    body_height = term_height - 4 - 1
    # 实测 box=ROUNDED + pad_edge + header 的固定开销恰好 4 行（顶框 1 + 表头 1 +
    # 底框 1 + pad_edge 边缘间距 1）；因此 body_capacity = body_height - 4 时 Table
    # 自然高度恰好等于 body_height，Live 完全不需要走 vertical_overflow=ellipsis
    # 路径，下边框永远钉在 body 底。
    table_overhead = 4
    body_capacity = max(0, body_height - table_overhead)

    # 关键设计：Table 必须恰好占据 body_height 行：
    #   - 行数过多：vertical_overflow="ellipsis" 会把下边框替成省略号（用户上一轮看到的）
    #   - 行数过少：body 下方出现无填充的空白带（更早一次看到的）
    # 解决：将数据行 clamp 到 body_capacity，差额用**空白行**补足。
    # 空白行保留 Table 的纵向骨架（边框/单元格依旧渲染），让 body 永远不会留下未填充区。
    news_in_view = min(len(news_list), body_capacity)
    table = build_news_table(news_list, max_rows=news_in_view)
    padding_rows = body_capacity - news_in_view
    if padding_rows > 0:
        for _ in range(padding_rows):
            table.add_row("", "", "", "")
    layout["body"].update(table)

    return layout


class TerminalUI:
    """终端 TUI 实时监控界面"""

    def __init__(
        self,
        interval: int,
        web_port: int = DEFAULT_WEB_PORT,
        restart_hotkey: bool = False,
    ):
        self._interval = interval
        self._web_port = web_port
        self._restart_hotkey = restart_hotkey
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
        # 内容签名缓存：仅当 cycle/total_news/new_count/status/news 列表头发生真实变化时才
        # 重建 Layout/Table；相同数据跳过整个 _render()，是治本消除「长跑抖动」的关键。
        # news 元组太重，只用首条 id + 末条 id + 总数作指纹，200 条命中同一窗口近乎稳态。
        self._last_signature: Optional[tuple] = None
        # Live 自身自带刷新线程（refresh_per_second），本 TUI 数据更新粒度 5s，
        # 把 auto-refresh 降到 1Hz 已经够响应 size 变更；再高就是无意义重绘抖动源。
        self._refresh_per_second = 1

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

    @staticmethod
    def _signature_of(news_list: List[NewsItem], cycle: int, total_news: int,
                      new_count: int, status: str, interval: int) -> tuple:
        """计算「与上一帧相比有无语义变化」指纹。

        不包含 now_str：时间戳在 header 里独立刷新（见 run()），与本指纹隔离；
        不包含 source_stats：键集稳定，循环本身已经更新 _build_source_stats 返回新 dict，
        但渲染侧没有 this 数据的展示位，带入会污染指纹让本优化失效。
        """
        n = len(news_list)
        head_id = news_list[0].id if n else 0
        tail_id = news_list[-1].id if n else 0
        return (cycle, total_news, new_count, status, interval, n, head_id, tail_id)

    def _has_visual_change(self) -> bool:
        """返回 True 表示需要重建 Layout；False 表示可直接复用上一次渲染结果。"""
        sig = self._signature_of(
            self._news_list, self._cycle, self._total_news,
            self._new_count, self._status, self._interval,
        )
        if sig != self._last_signature:
            self._last_signature = sig
            return True
        return False

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
            restart_hotkey=self._restart_hotkey,
        )

    def _size_changed(self) -> bool:
        """检测终端窗口尺寸是否变化"""
        current = (console.size.width, console.size.height)
        if current != self._last_size:
            self._last_size = current
            return True
        return False

    async def run(self):
        """启动 TUI 主循环（alternate screen 防闪烁）

        设计原则：
        1. **数据驱动的渲染**：只有 update_data() 触发或 resize 才会重建 Layout；
           Live 自带的内部刷新仅做 paint（diff 渲染），不重建 Tree，从根上消除「长跑抖动」。
        2. **时间戳每秒刷一次**：用专门的 tick 协程，时间变化时只 inject 新时间串到 header，
           不动 Table/Body，最大化减少重绘量。
        3. **不混用「事件刷新」+ 「refresh=True」**：原代码在 _update_event 到来时还
           调用 self._live.update(.., refresh=True)，与 Live 自身节拍叠加，是抖动源之一。
           现改为 update()，由 Live 自己按 refresh_per_second=1 决定 paint 时机。
        """
        self._running = True
        self._update_event.clear()
        self._last_size = (console.size.width, console.size.height)
        self._last_signature = None  # 首次必须渲染

        try:
            with Live(
                self._render(),
                console=console,
                screen=True,
                refresh_per_second=self._refresh_per_second,
                transient=False,
                vertical_overflow="ellipsis",
            ) as self._live:
                # 尺寸轮询节拍：0.2s。数据事件 5s 一次、Live 自带 1Hz paint，
                # 这里只负责「检测窗口尺寸变化」与「响应数据事件」，不重复渲染。
                # 拖动窗口时 GetConsoleScreenBufferInfo 粒度 ~100-200ms，0.2s
                # 足够跟手；再小只会白白增加系统调用。
                _SIZE_POLL_TIMEOUT = 0.2
                while self._running:
                    try:
                        # 等数据事件；超时不是异常，只代表这一拍没有新数据。
                        await asyncio.wait_for(
                            self._update_event.wait(),
                            timeout=_SIZE_POLL_TIMEOUT,
                        )
                    except asyncio.TimeoutError:
                        pass
                    self._update_event.clear()

                    if not self._running:
                        break

                    # 1) 尺寸变化 → 无条件重渲：body 高度依赖 console.size.height，
                    #    数据没变也必须 update()；同时清签名缓存，避免下一次数据
                    #    事件拿旧签名短路。
                    # 2) 数据变化 → 按指纹缓存决定是否重渲（内容没变就跳过最重的
                    #    _render()，这是治抖动的关键）。
                    # 顺序固定：先查尺寸，再查数据。拖拽与数据更新可以同一拍发生，
                    # 两个条件都满足时只渲染一次。
                    if self._size_changed():
                        self._last_signature = None
                        self._live.update(self._render())
                    elif self._has_visual_change():
                        # 不传 refresh=True：让 Live 自身的节拍决定 paint，
                        # 避免与自动重绘线程在 alt-screen buffer 上撞车。
                        self._live.update(self._render())
        except Exception as e:
            logger.debug(f"TUI 渲染异常: {e}")
        finally:
            # 退出 alt-screen 时强制恢复光标，避免老 conhost 在 SIGINT 后
            # 留下「光标被吞」的状态——这种状态在某些终端里也会让新进程输出抖动。
            try:
                console.show_cursor(True)
            except Exception:
                pass

    def stop(self):
        """停止 TUI"""
        self._running = False
        # set 而不是 clear：让阻塞在 wait_for 上的协程立刻被唤醒并走到 finally 分支
        self._update_event.set()
        if self._live:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None


def print_once_result(news_list: list[NewsItem], total_inserted: int, total_in_db: int, catch_up_cycles: int = 0):
    """单次模式打印结果"""
    news_list, _ = _filter_flash_only(news_list, {})
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
