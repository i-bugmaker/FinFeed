"""storage 层对外暴露的端口（Port）定义。

这里只声明**类型契约**，不引入任何实现依赖。上层通过「实现 Protocol +
启动时注入」的方式与 storage 协作，从而彻底切断 storage 对上层业务包的
反向依赖。

背景
----
重构前 `storage/database.py` 在函数内延迟导入了
`finfeed.analysis.importance.compute_importance` 与 `finfeed.market.store`，
使最底层的 storage 反向依赖上层业务包。配合 __init__ 的 import 副作用，
这些依赖环在运行时被「掩盖」而非解决，导致：

* 无法对依赖方向做静态检查（任何工具都会报环）
* 无法单独 import / 测试 storage（会连带拉起 analysis 与 market）
* 无法独立替换存储实现

改为端口 + 注入后，依赖方向反转为 `analysis → storage`（上层适配底层），
storage 成为真正的叶子包。
"""

from typing import Protocol, runtime_checkable

__all__ = ["ImportanceScorer"]


@runtime_checkable
class ImportanceScorer(Protocol):
    """新闻重要性打分端口。

    storage 在读取新闻时，若持久化的 importance 低于阈值（当前 2.0），
    会调用已注入的实现重新打分；未注入实现时保持原值并走兜底逻辑。

    实现方：finfeed.analysis.importance.compute_importance
    注入点：finfeed.core.pipeline（经由 storage.database 的装配函数）
    """

    def __call__(
        self,
        *,
        title: str,
        intro: str,
        source: str,
        stocks_count: int,
    ) -> float:
        """返回重要性分值（float，通常与新闻表 importance 列同量纲）。"""
        ...
