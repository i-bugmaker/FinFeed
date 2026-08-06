#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FinFeed 入口兼容层（薄壳）。

直接运行 `python main.py` 时转发到 finfeed.cli.main。
打包安装后由 pyproject.toml 的 [project.scripts] 直接调用 finfeed.cli:main。

入口逻辑唯一保留在 finfeed/cli.py，本文件仅做转发，避免重复代码。
"""
from finfeed.cli import main

if __name__ == "__main__":
    main()
