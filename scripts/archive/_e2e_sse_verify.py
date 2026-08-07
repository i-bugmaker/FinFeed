#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端（真实 SSE 套接字）验证增量推送修复。

不依赖 pytest，单独以脚本运行：python tests/_e2e_sse_verify.py
与运行时一致地把仓库根加入 sys.path（finfeed 目录本身不在 sys.path 上），
因此不会触发 finfeed/calendar 遮蔽标准库 calendar 的问题。

流程：
  1. 用临时库隔离（FINFEED_DB_PATH），写入 3 条基线新闻
  2. 启动真实 Web 服务（自动对齐推送水位线到基线最大 id）
  3. 启动一个真实 SSE 客户端监听 /api/events
  4. 插入 3 条新新闻，其中 1 条 publish_ts 刻意偏旧（模拟补抓/源时间戳滞后）
  5. 调用 broadcast_new_news()（增量推送唯一入口）
  6. 断言 SSE 客户端恰好收到 1 个 new_news 事件，count=3，
     且排序符合列表页口径（publish_ts DESC, id DESC），旧的 publish_ts 条目未被漏掉
  7. 断言 /api 数据（db_get_recent_news）已反映新增
"""

import json
import logging
import os
import sys
import tempfile
import threading
import time

import httpx

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

_TMP = tempfile.mkdtemp(prefix="finfeed_e2e_")
_TMP_DB = os.path.join(_TMP, "e2e.db")
os.environ["FINFEED_DB_PATH"] = _TMP_DB
os.environ["FINFEED_LOG_PATH"] = os.path.join(_TMP, "e2e.log")

# 抑制噪声日志，只保留关键结论
logging.getLogger("finfeed").setLevel(logging.ERROR)

from finfeed.config.settings import DB_PATH  # noqa: E402
from finfeed.storage.database import (  # noqa: E402
    init_db, db_insert_news, db_get_recent_news, db_get_max_news_id,
)
from finfeed.storage.models import NewsItem  # noqa: E402
from finfeed.ui.web import server as web  # noqa: E402
from finfeed.ui.web.server import (  # noqa: E402
    start_web_server, stop_web_server, broadcast_new_news,
)

assert DB_PATH == _TMP_DB, f"DB 隔离失败: {DB_PATH} != {_TMP_DB}"

PORT = 18099


def mk(title, publish_ts, category="finance"):
    return NewsItem(
        title=title,
        url=f"http://example.com/{title}",
        source="测试源",
        publish_time="",
        publish_ts=publish_ts,
        intro="",
        category=category,
    )


def main() -> int:
    # 1. 基线
    init_db()
    now = int(time.time())
    for i in range(3):
        db_insert_news([mk(f"base-{i}", now - 100 + i)])
    base_max = db_get_max_news_id("finance")
    print(f"[基线] 写入 3 条, finance 最大 id = {base_max}")

    # 2. 启动真实 Web 服务（内部会 init_broadcast_watermark 对齐到 base_max）
    server = start_web_server(PORT)
    time.sleep(0.5)

    # 3. 真实 SSE 客户端
    events: list = []
    ev_lock = threading.Lock()

    def sse_reader():
        try:
            with httpx.stream(
                "GET", f"http://127.0.0.1:{PORT}/api/events", timeout=30
            ) as resp:
                cur_event = None
                for line in resp.iter_lines():
                    if line.startswith("event:"):
                        cur_event = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        data = line[len("data:"):].strip()
                        if cur_event == "news":
                            try:
                                obj = json.loads(data)
                            except json.JSONDecodeError:
                                continue
                            if obj.get("type") == "new_news":
                                with ev_lock:
                                    events.append(obj)
        except Exception as e:  # noqa: BLE001
            print(f"[SSE reader] 异常: {e}")

    t = threading.Thread(target=sse_reader, daemon=True)
    t.start()
    time.sleep(1.0)  # 等连接建立（SSE 会先收到 connected 事件）

    # 4. 插入 3 条新新闻，其中 1 条 publish_ts 刻意偏旧
    specs = [("new-A", now), ("new-B", now + 1), ("old-ts", 1234)]
    for title, pts in specs:
        db_insert_news([mk(title, pts)])
    print(f"[插入] 新增 3 条 (new-A/publish_ts=now, new-B/now+1, old-ts/1234 偏旧)")

    # 5. 增量推送
    pushed = broadcast_new_news()
    print(f"[广播] broadcast_new_news() -> {pushed}")
    time.sleep(1.5)  # 等 SSE 投递

    # 6. 断言
    ok = True

    with ev_lock:
        new_news_events = [e for e in events if e.get("type") == "new_news"]
    if len(new_news_events) != 1:
        print(f"[FAIL] 期望恰好 1 个 new_news 事件, 实际 {len(new_news_events)} 个")
        ok = False
    else:
        ev = new_news_events[0]
        if ev.get("count") != 3:
            print(f"[FAIL] count 期望 3, 实际 {ev.get('count')}")
            ok = False
        titles = [it["title"] for it in ev.get("items", [])]
        # 排序口径：publish_ts DESC, id DESC -> new-B(now+1) 最前, 其次 new-A(now), 最后 old-ts(1234)
        if titles and titles[0] != "new-B":
            print(f"[FAIL] SSE 排序错误, 首条={titles[0] if titles else None}, 全部={titles}")
            ok = False
        if set(titles) != {"new-A", "new-B", "old-ts"}:
            print(f"[FAIL] SSE 漏条目, titles={titles}")
            ok = False
        if ev.get("truncated"):
            print("[FAIL] 少量新增不应置 truncated=True")
            ok = False
        if not ok:
            print(f"[DEBUG] 收到的事件: {json.dumps(new_news_events, ensure_ascii=False)[:800]}")

    # 7. API 数据面验证
    api_news = db_get_recent_news(limit=10, category="finance")
    api_titles = [n.title for n in api_news]
    for expected in ("new-A", "new-B", "old-ts"):
        if expected not in api_titles:
            print(f"[FAIL] /api 数据未反映新增 {expected}")
            ok = False

    # 8. 幂等：再次调用不应再推
    pushed2 = broadcast_new_news()
    if pushed2:
        print(f"[FAIL] 幂等失效, 二次调用又推送了 {pushed2}")
        ok = False

    stop_web_server()
    print("结果:", "E2E 通过 ✅" if ok else "E2E 失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
