#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pytest 引导文件。

1. 模块遮蔽根治说明（历史）：
   `finfeed/calendar` 包与标准库 `calendar` 同名，一旦 `finfeed/` 目录进入
   sys.path（pyproject.toml 的 `pythonpath = ["finfeed"]`），`import calendar`
   可能命中 finfeed.calendar 而非标准库，导致 httpx 内部
   `from calendar import timegm` 导入失败。
   该根因已于包重命名时根治：`finfeed/calendar` 已更名为 `finfeed/ecal`，
   因此这里不再需要任何 sys.path hack。

2. 测试数据库隔离：
   finfeed.config.settings 在模块导入时即固化 DB_PATH/LOG_PATH（读取
   FINFEED_* 环境变量）。为避免测试写穿到生产库，必须在导入任何 finfeed
   模块之前把这两个变量指向系统临时目录。conftest.py 由 pytest 最先加载，
   在收集任何测试模块之前执行，保证所有测试共享一个隔离的临时数据库。
"""

import os
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="finfeed_pytest_")
os.environ["FINFEED_DB_PATH"] = os.path.join(_TMP_DIR, "test.db")
os.environ["FINFEED_LOG_PATH"] = os.path.join(_TMP_DIR, "test.log")
