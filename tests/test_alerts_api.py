#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警推送 API 测试（FastAPI TestClient + 临时库）。

覆盖：webhooks CRUD、settings 读写、topics CRUD、推送日志、
校准结果读取、测试发送（mock 网络）。
"""


import finfeed.alerts.store as alert_store
import finfeed.storage.database as db_mod
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from finfeed.alerts.router import router


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_mod.DB_PATH = str(tmp_path / "test_alerts_api.db")
    db_mod._global_db = None
    monkeypatch.setattr(alert_store, "_tables_ready", False)
    # recent_push_log JOIN news、校准结果写 metadata，需要最小主库结构
    with db_mod.get_db_manager().get_db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT, url TEXT, source TEXT, publish_time TEXT
            );
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
    app = FastAPI()
    app.include_router(router)
    yield TestClient(app)
    db_mod._global_db = None


# ---------------------------------------------------------------------------
# webhooks CRUD
# ---------------------------------------------------------------------------

def test_webhook_crud_roundtrip(client):
    r = client.post("/api/alerts/webhooks", json={
        "name": "我的钉钉", "type": "dingtalk",
        "url": "https://oapi.dingtalk.com/robot/send?access_token=x",
    })
    assert r.status_code == 200
    wh = r.json()["webhook"]
    assert wh["id"] > 0 and wh["enabled"] is True

    r = client.put(f"/api/alerts/webhooks/{wh['id']}", json={
        "enabled": False, "min_importance": 7.5,
    })
    assert r.status_code == 200
    wh2 = r.json()["webhook"]
    assert wh2["enabled"] is False and wh2["min_importance"] == 7.5

    r = client.get("/api/alerts/webhooks")
    assert len(r.json()["webhooks"]) == 1

    r = client.delete(f"/api/alerts/webhooks/{wh['id']}")
    assert r.json()["ok"] is True
    r = client.get("/api/alerts/webhooks")
    assert r.json()["webhooks"] == []


def test_webhook_rejects_bad_type_and_empty_url(client):
    r = client.post("/api/alerts/webhooks", json={"type": "nope", "url": "http://x"})
    assert r.status_code == 400
    r = client.post("/api/alerts/webhooks", json={"type": "dingtalk", "url": "  "})
    assert r.status_code == 400


def test_webhook_update_missing_returns_404(client):
    r = client.put("/api/alerts/webhooks/999", json={"enabled": True})
    assert r.status_code == 404


def test_webhook_test_send_mocked(client, monkeypatch):
    r = client.post("/api/alerts/webhooks", json={
        "name": "测试渠道", "type": "wecom", "url": "https://qyapi.weixin.qq.com/x",
    })
    wid = r.json()["webhook"]["id"]

    import finfeed.alerts.router as router_mod

    async def fake_send(news_list, configs, matched_stocks=None, matched_topics=None):
        return {"success": 1, "failed": 0, "details": [{"name": "测试渠道", "ok": True, "error": ""}]}

    monkeypatch.setattr(router_mod, "send_webhook_news", fake_send)
    r = client.post(f"/api/alerts/webhooks/{wid}/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------

def test_settings_defaults_and_update(client):
    r = client.get("/api/alerts/settings")
    s = r.json()["settings"]
    assert s["enabled"] is True
    assert s["base_importance"] == 5.0

    r = client.put("/api/alerts/settings", json={
        "enabled": False, "base_importance": 6.5, "use_regime": False,
    })
    s = r.json()["settings"]
    assert s == {"enabled": False, "base_importance": 6.5,
                  "watchlist_min_importance": 0.0, "use_regime": False}

    # 非法键被忽略，不会破坏默认值结构
    r = client.put("/api/alerts/settings", json={"hacker_key": "1"})
    assert set(r.json()["settings"]) == {
        "enabled", "base_importance", "watchlist_min_importance", "use_regime"}


# ---------------------------------------------------------------------------
# topics
# ---------------------------------------------------------------------------

def test_topic_crud_roundtrip(client):
    r = client.post("/api/alerts/topics", json={
        "name": "新能源", "keywords": ["锂电", "光伏"], "description": "赛道跟踪",
    })
    assert r.status_code == 200
    t = r.json()["topic"]
    assert t["keywords"] == ["锂电", "光伏"]

    r = client.put(f"/api/alerts/topics/{t['id']}", json={"keywords": ["钠电"]})
    assert r.json()["topic"]["keywords"] == ["钠电"]

    r = client.delete(f"/api/alerts/topics/{t['id']}")
    assert r.json()["ok"] is True


def test_topic_create_requires_name_and_keywords(client):
    r = client.post("/api/alerts/topics", json={"name": "空关键词", "keywords": []})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 日志与校准
# ---------------------------------------------------------------------------

def test_logs_and_calibration_shape(client):
    r = client.get("/api/alerts/logs")
    assert r.json() == {"logs": []}

    # 校准结果未运行时为 None
    r = client.get("/api/alerts/calibration")
    assert r.json()["calibration"] is None

    # 写入一条模拟校准结果后再读
    import finfeed.analysis.crossref as crossref
    crossref.save_calibration_result({"by_label": {}, "by_source": {}, "sample": 12})
    r = client.get("/api/alerts/calibration")
    cal = r.json()["calibration"]
    assert cal["sample"] == 12 and "run_at" in cal

    r = client.get("/api/alerts/regime")
    assert r.json()["regime"]["regime"] in ("bull", "bear", "rotate", "normal")


def test_watchlist_endpoint_empty(client):
    r = client.get("/api/alerts/watchlist")
    assert r.status_code == 200
    assert r.json() == {"stocks": []}
