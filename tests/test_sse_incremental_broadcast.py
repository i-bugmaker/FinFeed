#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSE 增量推送正确性验证

覆盖历史缺陷：TUI 显示新闻已更新，但 Web 端不更新。

根因：用 `ORDER BY publish_ts DESC LIMIT total_new` 猜测「本轮新增条目」。
新抓取的条目发布时间可能偏旧（补抓、论坛旧帖、源时间戳滞后），会被挤出
该窗口 —— 推送出去的是旧条目，前端按 id 去重后无任何变化。

修复：改用 news.id（AUTOINCREMENT，与写入顺序严格一致）作为水位线。

运行: python tests/test_sse_incremental_broadcast.py
或:   python -m pytest tests/test_sse_incremental_broadcast.py -q
"""

import os
import sys
import time
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 双模式数据库隔离：
# - pytest 模式：conftest.py 最先加载，已设置 FINFEED_DB_PATH/FINFEED_LOG_PATH
#   指向临时目录，setdefault 不会覆盖，保证与其余测试共享同一隔离库。
# - 独立运行模式：conftest 未加载，此处兜底设置临时库，绝不触碰生产库。
_TMP_DIR = tempfile.mkdtemp(prefix="finfeed_sse_test_")
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
    init_db, db_insert_news, db_get_news_after_id, db_get_recent_news,
    db_get_max_news_id, db_close,
)
from finfeed.storage.models import NewsItem  # noqa: E402
from finfeed.ui.web import server as web  # noqa: E402


def _mk(title: str, publish_ts: int, category: str = "finance") -> NewsItem:
    return NewsItem(
        title=title,
        url=f"http://example.com/{title}",
        source="测试源",
        publish_time="",
        publish_ts=publish_ts,
        intro="",
        category=category,
    )


class _Recorder:
    """假 SSE 客户端：收集广播消息"""

    def __init__(self):
        self.msgs = []

    def install(self):
        # 注意：不能直接用 self.msgs.append —— drain() 若重绑定列表，
        # 已绑定的方法会继续写入旧对象。这里用 lambda 保证每次动态取值。
        web._sse_broadcast = lambda m: self.msgs.append(m)  # type: ignore[assignment]

    def drain(self):
        out = list(self.msgs)
        self.msgs.clear()
        return out


def main() -> int:
    init_db()
    now = int(time.time())
    failures = []
    rec = _Recorder()
    rec.install()

    def check(name, cond, detail=""):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))
        if not cond:
            failures.append(name)

    def titles(items):
        return [n.title for n in items]

    def pushed(msgs, category):
        for m in msgs:
            if m.get("category") == category:
                return [i["title"] for i in m["items"]], m.get("count", 0)
        return [], 0

    # ---------- 1. 基线 + 水位线初始化 ----------
    print("\n[1] 写入 5 条基线新闻，随后初始化推送水位线")
    db_insert_news([_mk(f"base-{i}", now - i) for i in range(5)])
    web.init_broadcast_watermark()
    base_wm = dict(web._broadcast_watermarks)
    out = web.broadcast_new_news()
    check("初始化后不会把历史库当成新增全量广播", out == {} and not rec.drain(),
          f"水位线={base_wm}, 返回={out}")

    # ---------- 2. 核心缺陷场景：新增条目发布时间偏旧 ----------
    print("\n[2] 新增 2 条『发布时间偏旧』的新闻（补抓 / 源时间戳滞后）")
    db_insert_news([_mk("late-A", now - 7200), _mk("late-B", now - 7300)])

    old_way = titles(db_get_recent_news(limit=2))          # 旧实现的取数方式
    check("复现缺陷：旧逻辑 publish_ts DESC LIMIT 2 取不到真正的新增",
          "late-A" not in old_way and "late-B" not in old_way,
          f"旧逻辑返回 {old_way}")

    out = web.broadcast_new_news()
    got, cnt = pushed(rec.drain(), "finance")
    check("修复后：精确广播这 2 条新增",
          sorted(got) == ["late-A", "late-B"] and cnt == 2 and out.get("finance") == 2,
          f"广播 {got}")

    # ---------- 3. 幂等性（即时推送 + 5s 兜底并存） ----------
    print("\n[3] 连续重复调用（模拟 push_callback 与兜底循环同时触发）")
    r1, r2 = web.broadcast_new_news(), web.broadcast_new_news()
    check("水位线推进后重复调用不再推送", r1 == {} and r2 == {} and not rec.drain(),
          f"{r1} / {r2}")

    # ---------- 4. 分类隔离 ----------
    print("\n[4] forum 帖子的高 id 不得挡住后续 finance 新闻")
    db_insert_news([_mk("forum-1", now, "forum"), _mk("forum-2", now, "forum")])
    web.broadcast_new_news()
    rec.drain()
    db_insert_news([_mk("fin-after-forum", now - 9000, "finance")])
    web.broadcast_new_news()
    got, _ = pushed(rec.drain(), "finance")
    check("finance 水位线不受 forum 高 id 干扰（原全局单水位线会永久漏播）",
          got == ["fin-after-forum"], f"广播 {got}")

    # ---------- 5. 大批量：截断标记 + 不丢条目 ----------
    print("\n[5] 新增量超出单条事件上限时，标记 truncated 并分批推完")
    n_burst = web.SSE_MAX_ITEMS_PER_EVENT + 8
    db_insert_news([_mk(f"burst-{i:03d}", now - 20000 - i) for i in range(n_burst)])
    web.broadcast_new_news()
    msgs = rec.drain()
    got, cnt = pushed(msgs, "finance")
    check("count 反映真实新增总数", cnt == n_burst, f"count={cnt}, 期望 {n_burst}")
    check("items 按上限截断且置 truncated=True",
          len(got) == web.SSE_MAX_ITEMS_PER_EVENT and msgs[0].get("truncated") is True,
          f"items={len(got)}, truncated={msgs[0].get('truncated')}")
    # burst-000 的 publish_ts 最大，应排在推送 payload 首位（与列表页
    # ORDER BY publish_ts DESC, id DESC 一致），而非按 id 倒序的 burst-057
    check("payload 排序键与列表页一致（publish_ts DESC）",
          got[0] == "burst-000", f"首条={got[0]}")

    print("\n[6] 分批拉取不丢条目（batch_limit < 新增量）")
    db_insert_news([_mk(f"tail-{i:02d}", now - 30000 - i) for i in range(12)])
    web._broadcast_watermarks["finance"] = db_get_max_news_id("finance") - 12
    collected, rounds = [], 0
    while rounds < 10:
        web.broadcast_new_news(batch_limit=5)
        msgs = rec.drain()
        if not msgs:
            break
        g, _ = pushed(msgs, "finance")
        collected += g
        rounds += 1
    check("分 5 条/批全部推完 12 条且无重复",
          len(collected) == 12 and len(set(collected)) == 12,
          f"{rounds} 批共 {len(collected)} 条")

    print("\n" + "=" * 60)
    if failures:
        print(f"结果: {len(failures)} 项失败 -> {failures}")
        return 1
    print("结果: 全部通过")
    return 0


def test_sse_incremental_broadcast() -> None:
    """SSE 增量推送正确性回归验证（pytest 入口）"""
    try:
        assert main() == 0
    finally:
        try:
            db_close()
        except Exception:
            pass


if __name__ == "__main__":
    code = 1
    try:
        code = main()
    finally:
        try:
            db_close()
        except Exception:
            pass
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
    sys.exit(code)
