"""全局 verbose 日志工具。

开启后，各处被静默吞掉的异常/丢弃的数据会以 [debug] 前缀输出到 stderr，
便于排查"为什么少了数据"。

Web 场景下用环境变量开启（原先由 CLI 的 --verbose 参数控制）：
    THS_F10_VERBOSE=1 python server.py
也可在代码中调用 set_verbose(True)。
"""

import os
import sys

_verbose = os.environ.get("THS_F10_VERBOSE", "") not in ("", "0", "false", "False")


def set_verbose(v):
    global _verbose
    _verbose = bool(v)


def is_verbose():
    return _verbose


def vlog(msg):
    if _verbose:
        print(f"[debug] {msg}", file=sys.stderr)
