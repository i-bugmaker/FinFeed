#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""财经新闻与舆情隔离验证

覆盖历史缺陷：在「财经新闻」端按来源（如「东方财富」）筛选时，会混入舆情(forum)数据。

根因：东方财富新闻（source=东方财富, category=finance）与东财股吧类舆情
（source=东方财富, category=forum）共享同一显示来源名。_serve_news 在指定来源时
只下发了 source 过滤、却丢弃了 category 过滤，导致按 source=东方财富 查询会把
舆情一并捞出。

修复：db_query_news 新增 category_exclude 参数；_serve_news 始终排除 forum。

运行: python tests/test_news_forum_isolation.py
或:   python -m pytest tests/test_news_forum_isolation.py -q
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 双模式数据库隔离：
# - pytest 模式：conftest.py 最先加载，已设置 FINFEED_DB_PATH/FINFEED_LOG_PATH
#   指向临时目录，setdefault 不会覆盖，保证与其余测试共享同一隔离库。
# - 独立运行模式：conftest 未加载，此处兜底设置临时库，绝不触碰生产库。
_TMP_DIR = tempfile.mkdtemp(prefix="finfeed_iso_test_")
_TMP_DB = os.path.join(_TMP_DIR, "test.db")
os.environ.setdefault("FINFEED_DB_PATH", _TMP_DB)
os.environ.setdefault("FINFEED_LOG_PATH", os.path.join(_TMP_DIR, "test.log"))

from finfeed.config.settings import DB_PATH  # noqa: E402

# 安全闸门：任何写操作前确认数据库位于系统临时目录，绝不触碰生产库
_DB_REAL = os.path.realpath(DB_PATH)
_TMP_ROOT = os.path.realpath(tempfile.gettempdir())
assert _DB_REAL == _TMP_ROOT or _DB_REAL.startswith(_TMP_ROOT + os.sep), (
    f"数据库隔离失败！当前 DB_PATH={DB_PATH} 不在临时目录（{_TMP_ROOT}）。"
    "已中止以避免污染生产数据。"
)

from finfeed.storage.database import (  # noqa: E402
    init_db, db_insert_news, db_query_news, db_close,
)
from finfeed.storage.models import NewsItem  # noqa: E402


def _mk(title: str, source: str, category: str, ts: int) -> NewsItem:
    return NewsItem(
        title=title,
        url=f"http://example.com/{title}",
        source=source,
        publish_time="",
        publish_ts=ts,
        intro="",
        category=category,
    )


def _run() -> None:
    init_db()
    # 东方财富新闻（finance）与东财股吧舆情（forum）共享显示来源名「东方财富」
    items = [
        _mk("东方财富快讯A", "东方财富", "finance", 1003),
        _mk("东方财富快讯B", "东方财富", "finance", 1002),
        _mk("东财股吧热帖X", "东方财富", "forum", 1001),   # 舆情
        _mk("东财股吧热帖Y", "东方财富", "forum", 1000),   # 舆情
        # 同花顺原创子栏目应为财经新闻（非 forum）
        _mk("同花顺原创盘评", "同花顺原创", "原创滚动盘评", 999),
    ]
    db_insert_news(items)

    # 1) 旧行为：仅按 source 过滤，不隔离舆情
    only_source, total_src = db_query_news(limit=100, source="东方财富")
    assert total_src == 4, f"仅按 source 过滤应返回 4 条（含舆情），实际 {total_src}"

    # 2) 修复后：按 source + 排除 forum，舆情不应泄漏
    fixed, fixed_total = db_query_news(
        limit=100, source="东方财富", category_exclude="forum"
    )
    assert fixed_total == 2, f"排除 forum 后应仅 2 条东方财富新闻，实际 {fixed_total}"
    assert all(i.category == "finance" for i in fixed), "财经新闻端混入了舆情(forum)"

    # 3) 默认财经新闻视图（category=finance）同样排除舆情
    default, default_total = db_query_news(limit=100, category="finance")
    assert all(i.category == "finance" for i in default), "默认视图混入了舆情(forum)"
    assert default_total == 2, f"默认 finance 视图应为 2 条东方财富新闻，实际 {default_total}"

    # 4) 按来源 + 排除 forum 不应误伤同花顺原创子栏目（category=原创滚动盘评，属财经新闻）
    ths, ths_total = db_query_news(
        limit=100, source="同花顺原创", category_exclude="forum"
    )
    assert ths_total == 1, f"同花顺原创子栏目应可见(非forum)，实际 {ths_total}"
    assert ths[0].category == "原创滚动盘评", "同花顺原创子栏目被错误隔离"

    print("OK: 财经新闻与舆情隔离验证通过")
    print(f"  - source=东方财富 仅过滤: {total_src} 条（含舆情，旧行为）")
    print(f"  - source=东方财富 + category_exclude=forum: {fixed_total} 条（已隔离）")
    print(f"  - category=finance 默认视图: {default_total} 条（已隔离）")
    print(f"  - source=同花顺原创 + category_exclude=forum: {ths_total} 条（子栏目未被误伤）")


def test_news_forum_isolation() -> None:
    """财经新闻与舆情隔离回归验证（pytest 入口）"""
    try:
        _run()
    finally:
        db_close()


if __name__ == "__main__":
    try:
        _run()
    finally:
        db_close()
