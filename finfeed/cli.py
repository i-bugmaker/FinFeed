#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ruff: noqa: E402 —— 下方包内 import 依赖 sys.path 注入（见第 28 行）
"""
FinFeed 实时新闻监控 - 主入口
===============================
模块化架构的新闻抓取、分析、推送系统。

用法:
    python main.py                     # 启动实时监控
    python main.py --interval 60       # 自定义抓取间隔
    python main.py --once              # 只抓取一次
    python main.py --export json       # 导出所有新闻为JSON
    python main.py --export csv        # 导出所有新闻为CSV
"""

import argparse
import asyncio
import logging
import logging.handlers
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("news_monitor")

from finfeed.config.settings import (
    DEFAULT_INTERVAL,
    DEFAULT_WEB_PORT,
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
)
from finfeed.core.monitor import get_monitor
from finfeed.storage.database import db_set_last_exit_ts, init_db
from finfeed.storage.exporter import (
    export_to_csv,
    export_to_excel,
    export_to_json,
    export_to_markdown,
    get_default_export_path,
)
from finfeed.ui.terminal import TerminalUI, print_once_result
from finfeed.ui.web_fastapi.shared import touch_sse_tick, update_web_state


async def run_once():
    """单次抓取模式"""
    monitor = get_monitor()
    total_new = await monitor.run_single_fetch()
    return total_new


async def run_continuous(interval: int, web_port: int):
    """持续监控模式（带TUI）"""
    monitor = get_monitor()
    terminal_ui = TerminalUI(
        interval=interval,
        web_port=web_port,
        restart_hotkey=bool(_hotkey_box and _hotkey_box.get("active")),
    )

    from finfeed.storage.database import (
        db_get_all_source_last_ts,
        db_get_recent_news,
        db_get_statistics,
    )

    def _build_source_stats() -> dict:
        return {src: 1 for src in db_get_all_source_last_ts()}

    async def push_callback(total_new):
        """抓取轮结束后的即时推送触发。

        增量条目由 FastAPI 子进程的 broadcast_new_news() 依据数据库自增 id
        水位线自行确定，这里不再自行猜测「哪几条是新的」。

        关键修复：monitor 运行在主进程，浏览器 SSE 连接注册在 FastAPI 子进程
        的 _sse_clients；主进程直接 broadcast_new_news() 只能推到自己进程的
        空客户端集合（对浏览器无效），且每轮浪费一次 DB 扫描。改为触碰 tick
        哨兵文件（finfeed/.finfeed_sse_tick），FastAPI 子进程监听到 mtime 变化
        即立即触发广播——推送延迟从 5s 盲轮询降到亚秒级，与 TUI 同级实时性。
        """
        try:
            touch_sse_tick()
        except Exception as e:
            logger.error(f"SSE tick 触发失败: {e}", exc_info=True)

        stats = db_get_statistics()
        # db_get_statistics() 的 key 是 "total_news"；误用 "total" 会恒为 0
        total_count = stats.get("total_news", 0)
        update_web_state(
            news=[],
            stats=_build_source_stats(),
            cycle=monitor.fetch_count,
            total=total_count,
            new_count=total_new,
            status=f"第{monitor.fetch_count}轮" if monitor.fetch_count > 0 else "运行中",
        )

    monitor.set_push_callback(push_callback)

    shutdown_event = asyncio.Event()

    def _signal_handler(signum, frame):
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError):
            pass

    async def update_tui():
        while not shutdown_event.is_set():
            try:
                # TUI 终端仅展示快讯（7×24 实时短消息）；文章类与舆情类不进入终端。
                # 快讯列表按 DB category='flash' 精确取数，与 terminal._filter_flash_only
                # 的来源过滤互为双保险（增量窗口内新入库条目的分类由解析器打标）。
                news = db_get_recent_news(limit=200, category="flash")
                stats = db_get_statistics()
                source_stats = _build_source_stats()
                # db_get_statistics() 返回的字典 key 是 "total_news"，
                # 不是 "total"——历史写法 get("total", 0) 会恒为 0，
                # 导致 TUI「库内 0 条」一直不更新（详见 push_callback 同注释）。
                total_count = stats.get("total_news", 0)

                status = "运行中" if monitor.is_running else "准备中"
                if monitor.fetch_count > 0:
                    status = f"第{monitor.fetch_count}轮"

                terminal_ui.update_data(
                    news_list=news,
                    cycle=monitor.fetch_count,
                    total_news=total_count,
                    new_count=monitor.total_new_count,
                    source_stats=source_stats,
                    status=status,
                )

                update_web_state(
                    news=[],
                    stats=source_stats,
                    cycle=monitor.fetch_count,
                    total=total_count,
                    new_count=monitor.total_new_count,
                    status=status,
                )

                # 兜底对账：push_callback 若因异常/时序问题漏推，这里 5 秒内
                # 再触碰一次 tick 文件，FastAPI 子进程据此立即补推。
                # broadcast_new_news 幂等（水位线单调），重复触发不会重复推送。
                touch_sse_tick()
            except Exception as e:
                logger.debug(f"TUI 更新异常: {e}")
            await asyncio.sleep(5)

    tui_task = asyncio.create_task(terminal_ui.run())
    update_task = asyncio.create_task(update_tui())
    monitor_task = asyncio.create_task(monitor.run())

    # 停止信号轮询：把两类外部停止请求转换为 shutdown_event（与
    # SIGINT/SIGTERM 同一优雅停机路径）：
    #   1) Ctrl+R 热键（_hotkey_restart_event，仅 Windows 控制台）；
    #   2) 重启请求哨兵文件（新实例重跑启动脚本时创建，跨平台生效，
    #      这是"重复启动 = 重启"语义的核心通道）。
    # 消费哨兵后以退出码 0 停机——不用 RESTART_EXIT_CODE，避免一键脚本
    # 把已被新实例接管的重启再循环触发一次。
    async def _stop_signal_poll():
        stop_file = (_hotkey_box or {}).get("stop_file")
        while not shutdown_event.is_set():
            if _hotkey_restart_event.is_set():
                shutdown_event.set()
                return
            if stop_file and os.path.exists(stop_file):
                print("\n[重启] 收到新实例的重启请求，正在优雅停止当前实例...")
                logger.info("收到重启请求哨兵: %s", stop_file)
                _remove_stop_file(stop_file)
                shutdown_event.set()
                return
            await asyncio.sleep(0.2)

    stop_signal_task = asyncio.create_task(_stop_signal_poll())

    await shutdown_event.wait()

    terminal_ui.stop()
    await monitor.shutdown()

    tasks = [monitor_task, tui_task, update_task, stop_signal_task]
    for task in tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    db_set_last_exit_ts(int(time.time()))


# Web 服务栈启动（FastAPI 单轨，8866）


def _launch_fastapi(port: int) -> "subprocess.Popen":
    """以独立子进程方式启动 FastAPI(ASGI) 服务，与主监控进程解耦。

    采用子进程而非线程：崩溃隔离更干净，且精确复现调试验证的启动命令
    ``python -m uvicorn finfeed.ui.web_fastapi.app:app --host :: --port PORT``。
    """
    cmd = [
        sys.executable, "-m", "uvicorn",
        "finfeed.ui.web_fastapi.app:app",
        "--host", "0.0.0.0",
        "--port", str(port),
        "--log-level", "info",
    ]
    logger.info("启动 FastAPI 服务(子进程): %s", " ".join(cmd))
    # 子进程输出重定向到**独立**的日志文件，避免与主进程 RotatingFileHandler
    # 共享同一个 fd 导致 doRollover 失败，进而在 TUI 顶部喷出
    # ``--- Logging error ---``（见 SafeRotatingFileHandler 注释）。
    log_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
    )
    child_log_path = os.path.join(log_dir, "finfeed_web.log")
    # 用 append + 显式 fileno 而非传文件对象：保证 关闭控制权 明确、子进程结束后
    # 我们的 write 也走同一个 fd，且 fd 由主进程独占，与 logger 的 RotatingFileHandler
    # 路径不同名 → 不再竞争。
    child_log_fd = os.open(child_log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    proc = subprocess.Popen(
        cmd,
        stdout=child_log_fd,
        stderr=child_log_fd,
        stdin=subprocess.DEVNULL,
        bufsize=0,
    )
    # subprocess 内部已 dup 了一个 fd，关闭我们手里的 fd 安全。
    # 保留这个 handle 让退出时能优雅 close。
    proc._finfeed_child_log_fd = child_log_fd  # type: ignore[attr-defined]
    return proc


def _terminate_fastapi(proc: "subprocess.Popen"):
    """优雅终止 FastAPI 子进程，超时则强制 kill。"""
    try:
        proc.terminate()
    except Exception as e:
        logger.debug("终止 FastAPI 子进程异常(可忽略): %s", e)
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    # 关闭我们持有的 child log fd（与子进程 stdout/stderr 关联），
    # 不留 fd 泄漏，让 OS 在文件句柄回收时干净。
    try:
        fd = getattr(proc, "_finfeed_child_log_fd", None)
        if fd is not None:
            os.close(fd)
            proc._finfeed_child_log_fd = None  # type: ignore[attr-defined]
    except Exception:
        pass


def start_web_stack(port: int) -> "subprocess.Popen | None":
    """启动 Web 服务栈（FastAPI 单轨）。

    - 仅 uvicorn(FastAPI) 监听 ``port``（默认 8866），由 ``finfeed.ui.web_fastapi.app`` 提供服务；
    - 旧的 stdlib ``server.py`` 已退役删除，SSE 广播通道由 ``ui.web_fastapi.shared`` 承载。
    - 依赖检查：uvicorn/fastapi 缺失时给出明确报错，不再静默降级。

    返回 FastAPI 子进程句柄（可能为 ``None``），供退出时回收。
    """
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        logger.error(
            "未检测到 uvicorn/fastapi，无法启动 Web 服务。"
            "请先安装依赖: pip install -e ."
        )
        raise SystemExit(1) from None
    proc = _launch_fastapi(port)
    # 重启场景防端口竞态：旧实例的 uvicorn 子进程刚被终止、端口尚未完全
    # 落地时，新子进程可能 bind 失败即退出。检测到"启动即退出"则短暂
    # 等待后重试一次。
    time.sleep(0.5)
    if proc.poll() is not None:
        logger.warning(
            "FastAPI 子进程启动即退出(退出码 %s)，疑似端口 %s 未释放，1 秒后重试一次",
            proc.returncode, port,
        )
        time.sleep(1.0)
        proc = _launch_fastapi(port)
    return proc


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """对 Windows 友好的日志轮转 handler，解决两个独立的现场问题：

    **问题 A — TUI 屏幕顶部冒出 ``--- Logging error ---``**：stdlib ``Handler.handleError()``
    在 handler 自身 ``emit()`` 抛异常时，会通过 ``sys.stderr.write()`` 把 fallback 信息写到
    stderr。在 ``Live(screen=True)`` 启用 alt-screen 时，stderr 仍然走当前 TTY，活动 buffer
    就是 alt buffer，于是该文本出现在 Rich 绘制的 header 之上一行，造成可见「抖动」。
    这里覆盖 ``handleError``，把诊断写到独立的 ``finfeed_errors.log`` 文件，永远不碰 stderr。

    **问题 B — 子进程与轮转的 fd 冲突**：FastAPI 子进程通过 ``open(log_path, "a")`` 持有
    ``finfeed.log`` 的 fd，Windows 上 ``RotatingFileHandler.doRollover`` 的 ``os.rename``
    会因此失败（其他进程持有句柄），同样会让 ``emit()`` 抛异常 → 触发「问题 A」。
    这里在 ``doRollover`` 失败时降级为「先关闭 + 重新打开」的策略，让 handler 仍能写入，
    同时把 maxBytes 临时上调避免高频抖动；不再让单条 log 的失败蔓延到整个进程。
    """

    _error_log_name = "finfeed_errors.log"

    def _log_dir(self) -> str:
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
        )

    def handleError(self, record):  # noqa: N802 - stdlib 命名
        """覆盖：永远不写 stderr，仅落到独立错误日志。"""
        try:
            err_path = os.path.join(self._log_dir(), self._error_log_name)
            os.makedirs(os.path.dirname(err_path), exist_ok=True)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(err_path, "a", encoding="utf-8") as fp:
                fp.write(
                    f"[{ts}] logging error in "
                    f"{self.__class__.__module__}.{self.__class__.__qualname__}\n"
                )
                et, ev, tb = sys.exc_info()
                if et is not None:
                    traceback.print_exception(et, ev, tb, limit=10, file=fp)
                fp.write(
                    f"  record: name={record.name!r} "
                    f"file={record.filename!r}:{record.lineno} "
                    f"msg={record.msg!r}\n"
                )
                fp.write("-" * 60 + "\n")
        except Exception:
            # 最后一关：连错误文件都写不动时静默，绝不让线程崩溃污染 TUI。
            pass

    def doRollover(self):  # noqa: N802 - stdlib 命名
        """容错版轮转：失败时降级为 close+reopen，handler 继续可用。"""
        try:
            super().doRollover()
            return
        except (OSError, PermissionError) as e:
            # 极可能是子进程仍持有 fd（Windows 不允许 rename 一个被独占打开的文件）。
            # 把这次失败记到错误日志，然后降级。
            try:
                err_path = os.path.join(self._log_dir(), self._error_log_name)
                os.makedirs(os.path.dirname(err_path), exist_ok=True)
                with open(err_path, "a", encoding="utf-8") as fp:
                    fp.write(
                        f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] doRollover failed, "
                        f"falling back to in-place reopen: {e!r}\n"
                    )
            except Exception:
                pass

        # 降级路径：关闭并以 append 模式原地重开，不 rotate。
        # 这样后续 emit() 不再抛，handler 仍能持续工作。
        try:
            if self.stream is not None:
                try:
                    self.stream.close()
                except Exception:
                    pass
                self.stream = None
            self.stream = self._open()
            # 把 maxBytes 临时上调 50%，避免下一条日志马上又试图触发 rollover。
            # 完全禁用（=0）会改变整盘语义，所以仅做缓冲上调。
            try:
                if self.maxBytes and self.maxBytes > 0:
                    self.maxBytes = int(self.maxBytes * 1.5)
            except Exception:
                pass
        except Exception:
            # 连 reopen 都不行：留下 None，让基类的 ensure_opened 逻辑下次再尝试。
            self.stream = None


def _setup_logging():
    """配置日志系统（SafeRotatingFileHandler：容错轮转 + 静默错误）"""
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "finfeed.log")
    # 仅写文件，不向控制台输出，避免黑窗口被日志刷屏
    file_handler = SafeRotatingFileHandler(
        log_file,
        encoding='utf-8',
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        delay=True,  # 延迟到首次 emit() 再开文件，减少 fd 占用时长
    )
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[file_handler],
    )
    # 防御性：移除 root 上任何残留的 StreamHandler（控制台输出源）
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.handlers.RotatingFileHandler):
            root.removeHandler(h)
    # asyncio 未检索的任务异常统一只写文件
    logging.getLogger("asyncio").propagate = True


# 单实例锁（2026-08-24 加固）


def _pid_alive(pid: int) -> bool:
    """检查 PID 是否存活（跨平台，不依赖 psutil）。

    注意：Windows 上禁止使用 ``os.kill(pid, 0)`` —— CPython 在 win32 的
    ``os.kill`` 对非 CTRL_* 信号走 ``TerminateProcess``，sig=0 会把目标
    进程直接杀掉而非探测存活。这里 Windows 走 OpenProcess 探测。
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == STILL_ACTIVE
                return True
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:
        return True
    return True


def _monitor_lock_path(instance: str = "") -> str:
    """锁文件路径。命名实例使用独立锁文件，默认实例保持原路径。"""
    filename = (
        f".finfeed_monitor_{instance}.lock" if instance else ".finfeed_monitor.lock"
    )
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "finfeed",
        filename,
    )


def _read_lock_pid(lock_path: str) -> int:
    """读取锁文件中记录的持有者 PID；损坏/缺失返回 0。"""
    try:
        with open(lock_path, "r", encoding="utf-8") as fp:
            return int(fp.read().strip() or "0")
    except (OSError, ValueError):
        return 0


def _stop_file_path(lock_path: str) -> str:
    """重启请求哨兵文件路径（位于锁文件旁）。"""
    return lock_path + ".stop"


def _request_graceful_stop(lock_path: str) -> None:
    """写入重启请求哨兵，旧实例轮询到后走优雅停机路径。"""
    try:
        with open(_stop_file_path(lock_path), "w", encoding="utf-8") as fp:
            fp.write(str(os.getpid()))
    except OSError as e:
        logger.warning(f"写入重启请求哨兵失败: {e}")


def _remove_stop_file(stop_file_path: str) -> None:
    """删除重启请求哨兵文件（参数为哨兵文件完整路径）。"""
    try:
        os.remove(stop_file_path)
    except OSError:
        pass


def _wait_process_exit(pid: int, timeout: float) -> bool:
    """轮询等待进程退出；超时返回 False。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.2)
    return not _pid_alive(pid)


def _force_kill_tree(pid: int) -> None:
    """强制终止进程及其子进程树（Windows 用 taskkill /T，POSIX 用 SIGKILL）。

    仅在旧实例未响应优雅停机时兜底使用——正常路径下旧实例会在自己的
    finally 中终止 FastAPI 子进程并保存状态，不会走到这里。
    """
    logger.warning(f"强制终止旧实例进程树 (PID {pid})")
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception as e:
        logger.warning(f"强制终止进程 {pid} 失败: {e}")


# 优雅停机等待上限：旧实例需完成 TUI 停止 / monitor 关停 / FastAPI 子进程
# 终止 / 状态保存。正常应在数秒内完成，25s 已含慢速抓取轮的收尾余量。
GRACEFUL_STOP_TIMEOUT = 25.0
# 强制终止后等待端口等系统资源释放的余量。
FORCE_KILL_WAIT = 10.0


def _acquire_monitor_lock(instance: str = "") -> Optional[str]:
    """获取实例锁（2026-08-28 重构：重启语义 + 多实例并存）。

    - **同一实例名重复启动 = 重启**：若锁持有者存活，写入 stop 哨兵文件
      请求旧实例优雅停止（旧实例轮询到后走与 Ctrl+C 完全相同的停机
      路径：TUI 停止、monitor 关停、FastAPI 子进程终止、状态保存、锁
      释放）；等待其退出，超时则强制终止进程树后接管。
    - **不同实例名并存运行**：各自使用独立锁文件 ``.finfeed_monitor_<NAME>.lock``。
    - **无运行中的旧实例**：按全新启动处理。
    """
    lock_path = _monitor_lock_path(instance)
    tag = f" [{instance}]" if instance else ""
    try:
        if os.path.exists(lock_path):
            old_pid = _read_lock_pid(lock_path)
            if old_pid > 0 and _pid_alive(old_pid):
                # 重启语义：请求旧实例优雅停止，而不是拒绝本实例启动。
                print(f"[重启] 检测到运行中的实例{tag} (PID {old_pid})，正在请求其优雅停止...")
                _request_graceful_stop(lock_path)
                if not _wait_process_exit(old_pid, GRACEFUL_STOP_TIMEOUT):
                    print(f"[重启] 旧实例 {GRACEFUL_STOP_TIMEOUT:.0f}s 内未响应，强制终止进程树...")
                    _force_kill_tree(old_pid)
                    if not _wait_process_exit(old_pid, FORCE_KILL_WAIT):
                        print("[ERROR] 无法终止旧实例，放弃启动以避免端口冲突与数据竞争。")
                        return None
                print("[重启] 旧实例已停止（状态已保存、端口已释放），继续启动。")
                time.sleep(0.3)  # 端口等系统资源完全落地的微小余量
            elif old_pid > 0:
                logger.warning(f"接管失效监控锁{tag}（旧 PID {old_pid}）")
        with open(lock_path, "w", encoding="utf-8") as fp:
            fp.write(str(os.getpid()))
        # 清理可能残留的重启请求哨兵：旧实例被强制终止时未来得及消费，
        # 若不清除，本实例的轮询任务会立刻误判为"收到重启请求"而自停。
        _remove_stop_file(_stop_file_path(lock_path))
        return lock_path
    except OSError as e:
        logger.warning(f"监控锁创建失败（忽略，继续启动）: {e}")
        return None


def _release_monitor_lock(lock_path: Optional[str]) -> None:
    """释放单实例锁（仅当持有者仍是本进程时删除）。"""
    if not lock_path:
        return
    try:
        if os.path.exists(lock_path):
            with open(lock_path, "r", encoding="utf-8") as fp:
                pid = int(fp.read().strip() or "0")
            if pid == os.getpid():
                os.remove(lock_path)
    except Exception:
        pass


# Ctrl+R 一键重启热键（2026-08-28）

# 重启约定退出码：监控进程以此码退出时，一键脚本据此自动重启。
RESTART_EXIT_CODE = 42

# 热键触发信号：监听线程置位，run_continuous 内的轮询任务将其转换为
# shutdown_event（与 SIGINT/SIGTERM 同一优雅停机路径）。
_hotkey_restart_event = threading.Event()
# 当前实例的热键状态盒（由 _start_restart_hotkey 赋值，run_continuous 读取）。
_hotkey_box: Optional[dict] = None


def _start_restart_hotkey() -> dict:
    """启动 Ctrl+R 重启热键监听（仅 Windows 控制台生效）。

    后台守护线程通过 msvcrt 读取按键：Ctrl+R（0x12）或 r/R 触发后置位
    ``_hotkey_restart_event``；run_continuous 的轮询任务检测到后设置
    shutdown_event，走与 Ctrl+C 完全相同的优雅停机（TUI 停止、monitor
    关停、锁释放），随后进程以 RESTART_EXIT_CODE 退出，由一键脚本接管重启。

    返回状态盒 box：box["active"] 表示监听线程是否已启动；box["restart"]
    在触发后置位，main 据此决定退出码。非 Windows / 非终端环境不监听。
    """
    global _hotkey_box
    box = {"restart": False, "active": False}
    _hotkey_box = box
    _hotkey_restart_event.clear()
    if sys.platform != "win32":
        return box
    try:
        import msvcrt

        if not sys.stdin or not sys.stdin.isatty():
            return box
    except Exception:
        return box

    def _watch():
        while True:
            try:
                ch = msvcrt.getch()
            except OSError:
                return
            if ch in (b"\x12", b"r", b"R"):  # b"\x12" = Ctrl+R
                box["restart"] = True
                _hotkey_restart_event.set()
                print("\n[快捷键] Ctrl+R 已触发，正在优雅停止并重启监控...")
                return

    try:
        threading.Thread(
            target=_watch, name="hotkey-restart", daemon=True
        ).start()
        box["active"] = True
    except Exception:
        pass
    return box


def _run_market_action(args):
    """事实层 CLI 调度。"""
    from finfeed.analysis import crossref
    from finfeed.market import alerts as mk_alerts
    from finfeed.market import report as mk_report
    from finfeed.market import service as mkt

    mkt.init_market()
    action = args.market
    date = args.date
    if action == "init":
        print("事实层数据表已就绪")
    elif action == "universe":
        res = mkt.run_universe_sync()
        print(f"股票池/板块刷新: {res}")
    elif action == "snapshot":
        res = mkt.run_daily_snapshot_sync(date)
        print(f"盘后快照: {res}")
    elif action == "bars":
        # collect_bars_sync 返回 {codes, done, rows, aborted}，不是行数
        res = mkt.collect_bars_sync(date, args.limit or None)
        msg = (f"日线采集: 计划 {res['codes']} 只 / 完成 {res['done']} 只 / "
               f"写入 {res['rows']} 行")
        if res.get("aborted"):
            msg += "（因 push2his 限流提前中断）"
        print(msg)
    elif action == "backfill":
        n = crossref.run_backfill()
        print(f"news_stock_link 回填 {n} 条")
    elif action == "calibrate":
        rep = crossref.run_calibrate()
        print("情感闭环校准结果:")
        print(f"  样本数: {rep.get('sample')}")
        for label, v in rep.get("by_label", {}).items():
            print(f"  [{label}] n={v['n']} 平均T+1收益={v['avg_ret']} 胜率={v['win_rate']}")
    elif action == "report":
        print(mk_report.run_report(date))
    elif action == "alerts":
        print(mk_alerts.regime_summary(date))
    else:
        print(f"未知事实层指令: {action}")


def _run_screener_action(args):
    """选股模块 CLI 调度。"""
    from finfeed.screener import cli as screener_cli
    return screener_cli.cmd_screener(args)


def main():
    _setup_logging()

    parser = argparse.ArgumentParser(
        description="FinFeed 实时新闻监控",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                      # 启动实时监控（默认 FastAPI 单轨，8866）
  python main.py --interval 60        # 每60秒抓取一次
  python main.py --once               # 只抓取一次
  python main.py --web-only           # 仅起 Web（无浏览器环境预览新界面）
  python main.py --export json        # 导出为JSON
  python main.py --export csv         # 导出为CSV
  python main.py --export json --start 2024-01-01 --end 2024-01-31
  python main.py --instance b2        # 命名实例（独立锁文件，端口自动派生，可多实例并行）
  python main.py --instance b2 --port 8877   # 命名实例并显式指定端口
        """
    )
    parser.add_argument("--port", type=int, default=None, help=f"Web 仪表盘端口（默认 {DEFAULT_WEB_PORT}；命名实例未指定时按实例名自动派生）")
    parser.add_argument("--instance", default="", help="命名实例：使用独立锁文件 .finfeed_monitor_<NAME>.lock，允许多实例并行（注意共享同一数据库，避免同时对同一批源做重补抓）")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL, help=f"抓取间隔（秒），默认{DEFAULT_INTERVAL}")
    parser.add_argument("--once", action="store_true", help="只抓取一次后退出")
    parser.add_argument("--export", choices=["json", "csv", "excel", "markdown", "md"], help="导出格式 (json/csv/excel/markdown)")
    parser.add_argument("--output", "-o", help="导出文件路径（默认自动生成）")
    parser.add_argument("--start", help="导出起始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", help="导出截止日期 (YYYY-MM-DD)")
    parser.add_argument(
        "--market", metavar="ACTION",
        choices=["init", "universe", "snapshot", "bars", "backfill", "calibrate", "report", "alerts"],
        help="事实层指令: init(建表) universe(股票池+板块) snapshot(盘后快照) "
             "bars(日线回补) backfill(历史新闻关联) calibrate(情感校准) report(涨停归因) alerts(市场状态)",
    )
    parser.add_argument("--date", help="事实层指令所用交易日 (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=0, help="bars 回补数量上限")
    parser.add_argument(
        "--web", choices=["fastapi"], default="fastapi",
        help="Web 后端: 仅 FastAPI 单轨（端口见 --port）。",
    )
    parser.add_argument(
        "--web-only", action="store_true",
        help="仅启动 Web 服务（不运行监控器）。无浏览器环境下可稳定预览新界面；Ctrl+C 停止。无实时推送，但可浏览已有数据。",
    )

    # 选股模块（finfeed.screener）参数
    from finfeed.screener import cli as screener_cli
    screener_cli.add_arguments(parser)

    args = parser.parse_args()

    # 端口解析：未显式指定时，默认实例用 8866；命名实例按实例名稳定派生
    # （8867-9266，同名实例重启端口不变，便于书签/外部跳转）。
    if args.port is None:
        if args.instance:
            import zlib

            offset = 1 + (zlib.crc32(args.instance.encode("utf-8")) % 400)
            args.port = DEFAULT_WEB_PORT + offset
        else:
            args.port = DEFAULT_WEB_PORT

    init_db()

    if args.market:
        _run_market_action(args)
        return

    if args.screener:
        _run_screener_action(args)
        return

    if args.export:
        fmt = "markdown" if args.export == "md" else args.export
        output_path = args.output or get_default_export_path(fmt)
        if fmt == "json":
            count = export_to_json(output_path, args.start, args.end)
        elif fmt == "csv":
            count = export_to_csv(output_path, args.start, args.end)
        elif fmt == "excel":
            count = export_to_excel(output_path, args.start, args.end)
        elif fmt == "markdown":
            count = export_to_markdown(output_path, args.start, args.end)
        else:
            count = 0
        print(f"\n导出完成: {count} 条新闻已保存到 {output_path}")
        return

    if args.web_only:
        fastapi_proc = start_web_stack(args.port)
        print("\nWeb 服务已启动（后台运行，日志仅写入 logs/finfeed.log）：")
        print(f"  界面:    http://127.0.0.1:{args.port}/")
        print(f"  API文档: http://127.0.0.1:{args.port}/docs")
        print("  按 Ctrl+C 停止。")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nWeb 服务已停止。")
        finally:
            if fastapi_proc is not None:
                _terminate_fastapi(fastapi_proc)
            db_set_last_exit_ts(int(time.time()))
        return

    monitor = get_monitor()

    def _signal_handler(signum, frame):
        asyncio.get_event_loop().call_soon_threadsafe(
            lambda: asyncio.create_task(monitor.shutdown())
        )

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _signal_handler)
        except (ValueError, OSError):
            pass

    fastapi_proc = None
    lock_path = None
    box = {"restart": False, "active": False}
    try:
        if args.once:
            fastapi_proc = start_web_stack(args.port)
            total_new = asyncio.run(run_once())
            print_once_result([], total_new, 0, 0)
        else:
            # 实例锁（2026-08-28 重启语义）：同名实例重复启动 = 自动停止旧
            # 实例后重启；不同实例名使用独立锁文件，可并存运行。
            # 锁必须先于 Web 栈获取：重启场景下旧实例仍占用 Web 端口，
            # 先停旧实例再启动 uvicorn，否则端口冲突导致 Web 起不来。
            lock_path = _acquire_monitor_lock(args.instance)
            if lock_path is None:
                print("\n[ERROR] 无法获取实例锁（旧实例强制终止失败），放弃启动。")
                print("        请手动检查进程后重试，或删除 "
                      f"{lock_path} 及其 .stop 文件。")
                sys.exit(1)
            box = _start_restart_hotkey()
            box["stop_file"] = _stop_file_path(lock_path)
            if args.instance:
                print(f"[OK] 命名实例 [{args.instance}] 已就绪，Web 端口 {args.port}")
            fastapi_proc = start_web_stack(args.port)
            asyncio.run(run_continuous(interval=args.interval, web_port=args.port))
            if box.get("restart"):
                # 约定退出码：一键脚本检测到 42 后自动重启本进程。
                sys.exit(RESTART_EXIT_CODE)
    except KeyboardInterrupt:
        print("\n监控已停止。数据已持久化。")
    finally:
        if fastapi_proc is not None:
            _terminate_fastapi(fastapi_proc)
        db_set_last_exit_ts(int(time.time()))
        _release_monitor_lock(lock_path)


if __name__ == "__main__":
    main()
