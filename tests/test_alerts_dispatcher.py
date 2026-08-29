#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警分发器测试（临时库 + monkeypatch，不发真实网络请求）。

覆盖：
- 免打扰时段判定（含跨零点区间）
- 匹配与阈值过滤（自选股阈值 / 主题动态阈值）
- 分发主流程：开关、渠道分组、幂等去重、安静时段跳过
"""

import asyncio

import pytest

import finfeed.alerts.dispatcher as dispatcher
import finfeed.alerts.store as alert_store
import finfeed.storage.database as db_mod
from finfeed.alerts.dispatcher import _evaluate_news, _in_quiet_hours, dispatch_news_alerts
from finfeed.storage.models import NewsItem


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db_mod.DB_PATH = str(tmp_path / "test_alerts.db")
    db_mod._global_db = None
    monkeypatch.setattr(alert_store, "_tables_ready", False)
    _init_min_schema()
    yield db_mod.DB_PATH
    db_mod._global_db = None


def _init_min_schema():
    """alerts 模块依赖主库的 news 表与市场情绪表；测试库补最小结构。"""
    with db_mod.get_db_manager().get_db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, url TEXT, source TEXT, publish_time TEXT
            );
            CREATE TABLE IF NOT EXISTS market_sentiment_daily (
                trade_date TEXT PRIMARY KEY,
                breadth REAL DEFAULT 0,
                up_limit INTEGER DEFAULT 0,
                down_limit INTEGER DEFAULT 0
            );
        """)


def _news(nid: int, title: str = "测试新闻", stocks: list = None,
          importance: float = 8.0) -> NewsItem:
    return NewsItem(
        id=nid, title=title, url=f"http://x/{nid}", source="测试源",
        publish_time="2026-08-29 10:00:00", publish_ts=0, intro="",
        importance=importance, stocks=stocks or [],
    )


# ---------------------------------------------------------------------------
# 免打扰时段
# ---------------------------------------------------------------------------

def test_quiet_hours_empty_config_is_never_quiet():
    assert _in_quiet_hours({"quiet_start": "", "quiet_end": ""}) is False


def test_quiet_hours_within_window():
    import datetime
    now = datetime.datetime(2026, 8, 29, 23, 0)
    assert _in_quiet_hours({"quiet_start": "22:00", "quiet_end": "08:00"}, now) is True
    assert _in_quiet_hours({"quiet_start": "22:00", "quiet_end": "08:00"},
                            datetime.datetime(2026, 8, 29, 12, 0)) is False


def test_quiet_hours_cross_midnight():
    import datetime
    cfg = {"quiet_start": "22:30", "quiet_end": "08:00"}
    assert _in_quiet_hours(cfg, datetime.datetime(2026, 8, 29, 23, 30)) is True
    assert _in_quiet_hours(cfg, datetime.datetime(2026, 8, 29, 7, 59)) is True
    assert _in_quiet_hours(cfg, datetime.datetime(2026, 8, 29, 8, 0)) is False


def test_quiet_hours_invalid_config_falls_back_to_false():
    import datetime
    assert _in_quiet_hours({"quiet_start": "xx", "quiet_end": "08:00"},
                            datetime.datetime(2026, 8, 29, 23, 0)) is False


# ---------------------------------------------------------------------------
# 匹配与阈值
# ---------------------------------------------------------------------------

def test_evaluate_watchlist_hit_respects_min_importance(monkeypatch):
    monkeypatch.setattr(dispatcher, "match_watchlist_news",
                        lambda stocks: stocks)
    monkeypatch.setattr(dispatcher, "match_topics_news", lambda t, i: [])
    settings = {"base_importance": 5.0, "watchlist_min_importance": 6.0, "use_regime": False}

    alert_items, _ = _evaluate_news(
        [_news(1, stocks=["600000"], importance=7.0),
         _news(2, stocks=["600000"], importance=3.0)],
        settings,
    )
    assert [a["item"].id for a in alert_items] == [1]


def test_evaluate_topic_uses_regime_multiplier(monkeypatch):
    monkeypatch.setattr(dispatcher, "match_watchlist_news", lambda stocks: [])
    monkeypatch.setattr(dispatcher, "match_topics_news",
                        lambda t, i: [{"id": 9, "name": "新能源"}] if "电池" in t else [])
    monkeypatch.setattr("finfeed.market.alerts.threshold_multiplier", lambda: 1.2)

    alert_items, topics = _evaluate_news(
        [_news(1, title="固态电池突破", importance=5.0),   # 5.0 < 5.0*1.2 → 不推
         _news(2, title="固态电池突破", importance=6.5)],  # 6.5 ≥ 6.0 → 推
        {"base_importance": 5.0, "watchlist_min_importance": 0.0, "use_regime": True},
    )
    assert [a["item"].id for a in alert_items] == [2]
    assert 9 in topics


def test_evaluate_no_match_returns_empty(monkeypatch, tmp_db):
    monkeypatch.setattr(dispatcher, "match_watchlist_news", lambda stocks: [])
    monkeypatch.setattr(dispatcher, "match_topics_news", lambda t, i: [])
    settings = {"base_importance": 5.0, "watchlist_min_importance": 0.0, "use_regime": False}
    alert_items, _ = _evaluate_news([_news(1)], settings)
    assert alert_items == []


# ---------------------------------------------------------------------------
# 分发主流程
# ---------------------------------------------------------------------------

def test_dispatch_disabled_returns_none(tmp_db, monkeypatch):
    alert_store.ensure_tables()
    alert_store.update_settings({"enabled": False})
    assert _run(dispatch_news_alerts([_news(1)])) is None


def test_dispatch_no_channels_returns_none(tmp_db):
    alert_store.ensure_tables()
    assert _run(dispatch_news_alerts([_news(1)])) is None


def test_dispatch_pushes_and_dedups(tmp_db, monkeypatch):
    alert_store.ensure_tables()
    alert_store.create_webhook({"name": "钉钉群", "type": "dingtalk",
                                 "url": "https://oapi.dingtalk.com/robot/send?x=1"})
    monkeypatch.setattr(dispatcher, "match_watchlist_news", lambda stocks: stocks)
    monkeypatch.setattr(dispatcher, "match_topics_news", lambda t, i: [])

    sent = []

    async def fake_send(news_list, configs, matched_stocks=None, matched_topics=None):
        sent.append([n.id for n in news_list])
        return {"success": 1, "failed": 0, "details": [{"name": "x", "ok": True, "error": ""}]}

    monkeypatch.setattr(dispatcher, "send_webhook_news", fake_send)

    # watchlist_min_importance=5.0：item2 重要性 3.0 被过滤，item1(8.0) 通过
    alert_store.update_settings({"watchlist_min_importance": 5.0})
    items = [_news(1, stocks=["600000"]), _news(2, stocks=["600000"], importance=3.0)]
    res = _run(dispatch_news_alerts(items))
    assert res["alerted"] == 1 and res["pushed"] == 1
    assert sent == [[1]]

    # 幂等：同一新闻再次分发不再推送
    res2 = _run(dispatch_news_alerts([_news(1, stocks=["600000"])]))
    assert res2["pushed"] == 0
    assert len(sent) == 1


def test_dispatch_respects_channel_min_importance(tmp_db, monkeypatch):
    alert_store.ensure_tables()
    alert_store.create_webhook({"name": "高阈值群", "type": "wecom",
                                 "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook?key=1",
                                 "min_importance": 9.0})
    monkeypatch.setattr(dispatcher, "match_watchlist_news", lambda stocks: stocks)
    monkeypatch.setattr(dispatcher, "match_topics_news", lambda t, i: [])

    sent = []

    async def fake_send(news_list, configs, matched_stocks=None, matched_topics=None):
        sent.append([n.id for n in news_list])
        return {"success": 1, "failed": 0, "details": []}

    monkeypatch.setattr(dispatcher, "send_webhook_news", fake_send)

    res = _run(dispatch_news_alerts([_news(1, stocks=["600000"], importance=8.0)]))
    # 8.0 < 渠道 min_importance 9.0 → 该渠道无候选，未推送（新闻本身仍计入 alerted）
    assert res["pushed"] == 0
    assert sent == []


def test_dispatch_skips_quiet_hours_channel(tmp_db, monkeypatch):
    alert_store.ensure_tables()
    alert_store.create_webhook({"name": "夜间静默", "type": "feishu",
                                 "url": "https://open.feishu.cn/open-apis/bot/v2/hook/x",
                                 "quiet_start": "00:00", "quiet_end": "23:59"})
    monkeypatch.setattr(dispatcher, "match_watchlist_news", lambda stocks: stocks)
    monkeypatch.setattr(dispatcher, "match_topics_news", lambda t, i: [])
    # dispatcher 以 from-import 持有 now_bj 引用，须在 dispatcher 命名空间打补丁
    monkeypatch.setattr(dispatcher, "now_bj",
                        lambda: __import__("datetime").datetime(2026, 8, 29, 12, 0))

    sent = []

    async def fake_send(news_list, configs, matched_stocks=None, matched_topics=None):
        sent.append(1)
        return {"success": 1, "failed": 0, "details": []}

    monkeypatch.setattr(dispatcher, "send_webhook_news", fake_send)
    res = _run(dispatch_news_alerts([_news(1, stocks=["600000"])]))
    # 全天免打扰 → 渠道被跳过（news_id 也不记录，静默期结束后不会被补推旧闻）
    assert res == {"evaluated": 1, "alerted": 1, "pushed": 0, "failed": 0}
    assert sent == []


def test_schedule_dispatch_without_loop_is_noop():
    # 无事件循环时不抛异常（管线在异步上下文外调用的兜底）
    dispatcher.schedule_dispatch([_news(1)])
