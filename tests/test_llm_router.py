#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 路由冒烟测试（FastAPI TestClient + 临时库）。

验证：路由注册齐全、ApiError 统一错误合同、Pydantic 校验、
任务事件 SSE 端点的基础行为。不发起真实 LLM 调用。
"""

import finfeed.storage.database as db_mod
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from finfeed.llm import schema as llm_schema
from finfeed.ui.web_fastapi.core.errors import install_exception_handlers
from finfeed.ui.web_fastapi.routers.llm import create_router


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_mod.DB_PATH = str(tmp_path / "test_llm_router.db")
    db_mod._global_db = None
    # 重置建表缓存：否则前一个用例的 _initialized=True 会让新临时库跳过建表
    monkeypatch.setattr(llm_schema, "_initialized", False)
    yield
    db_mod._global_db = None


def _make_client() -> TestClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(create_router())
    return TestClient(app)


EXPECTED_GET_ROUTES = {
    "/api/llm/status", "/api/llm/init", "/api/llm/presets", "/api/llm/prompts",
    "/api/llm/providers", "/api/llm/provider", "/api/llm/preview",
    "/api/llm/task", "/api/llm/tasks", "/api/llm/task/retry",
    "/api/llm/sessions", "/api/llm/sessions/messages",
    "/api/llm/reports", "/api/llm/report", "/api/llm/report/export",
    "/api/llm/task/stream",
}


def test_router_registers_all_legacy_public_urls():
    paths = {r.path for r in create_router().routes}
    assert EXPECTED_GET_ROUTES <= paths


def test_presets_endpoint_shape(client):
    r = _make_client().get("/api/llm/presets")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["presets"], list) and body["presets"]
    assert {s["key"] for s in body["scopes"]} >= {"all", "finance", "forum"}
    assert 24 in body["windows"]


def test_prompts_defaults_exposed(client):
    r = _make_client().get("/api/llm/prompts")
    keys = set(r.json()["defaults"])
    assert {"map_system", "map_user", "reduce_system", "reduce_user", "single_user"} <= keys


def test_api_error_contract_on_missing_provider(client):
    r = _make_client().get("/api/llm/provider?id=99999")
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert isinstance(body["error"]["message"], str)


def test_query_validation_rejects_out_of_range_window(client):
    r = _make_client().get("/api/llm/preview?hours=9999")
    assert r.status_code == 422


def test_analyze_without_providers_returns_conflict_result_shape(client):
    """空库提交：保持旧「操作结果」形状 409 {ok:false,...}，前端据此提示配置模型。"""
    r = _make_client().post(
        "/api/llm/analyze",
        json={"hours": 24, "scope": "all"},
    )
    assert r.status_code == 409
    body = r.json()
    assert body["ok"] is False
    assert "大语言模型" in body["error"]


def test_analyze_validation_error_is_422_contract(client):
    r = _make_client().post("/api/llm/analyze", json={"hours": 0})
    assert r.status_code == 422


def test_task_stream_unknown_task_returns_404(client):
    r = _make_client().get("/api/llm/task/stream?id=nonexistent-task-id")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_chat_requires_question(client):
    r = _make_client().post("/api/llm/chat", json={"report_id": 0, "question": "  "})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION"


def test_provider_save_missing_fields_maps_domain_valueerror(client):
    r = _make_client().post("/api/llm/provider/save", json={"name": ""})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "VALIDATION"


def test_sessions_crud_roundtrip(client):
    c = _make_client()
    created = c.post("/api/llm/sessions", json={"title": "测试会话"})
    assert created.status_code == 200
    sid = created.json()["session"]["id"]

    listed = c.get("/api/llm/sessions").json()["sessions"]
    assert any(s["id"] == sid for s in listed)

    renamed = c.post("/api/llm/sessions/rename", json={"id": sid, "title": "改名"})
    assert renamed.json()["success"] is True

    deleted = c.post("/api/llm/sessions/delete", json={"id": sid})
    assert deleted.json()["success"] is True

    gone = c.post("/api/llm/sessions/rename", json={"id": sid, "title": "x"})
    assert gone.status_code == 404
