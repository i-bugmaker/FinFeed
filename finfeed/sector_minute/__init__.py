"""板块分时监控子包。

刻意保持 `__init__.py` 为空（零副作用）：上层 `ui/web_fastapi/app.py` 以
`try / except ImportError` 方式可选装配本模块，若在此处导入子模块，
会在 easy-tdx 等可选依赖缺失时破坏优雅降级逻辑。

历史说明：本包此前缺少 `__init__.py`，仅靠 PEP 420 命名空间包运行。
这导致 `setuptools.packages.find` 无法收录本包，打包（wheel / 安装部署）
时会整体丢失。现补齐为常规包。
"""
