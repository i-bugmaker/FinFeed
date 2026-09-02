#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""洞察任务引擎与 SSE 订阅测试。

覆盖：finfeed.llm.insight.InsightService 的提交/缓存/取消/失败语义，
以及 /api/llm/insight/stream 在真实高频增量下的连接寿命（回归防护：
SSE 空闲计时曾把高频 delta 折算进“空闲”，约 140 个事件即提前掐断连接，
修复后按单调时钟计真实存活时长）。
不发起任何真实 LLM 调用。
"""

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from finfeed.llm import insight
from finfeed.llm.client import LLMError
from finfeed.ui.web_fastapi.core.errors import install_exception_handlers
from finfeed.ui.web_fastapi.routers.llm import create_router, publish_llm_task_event

# ---------------------------------------------------------------- 桩实现

def _provider(**kw):
    base = dict(
        id=1, name="stub", model="stub-model", base_url="http://127.0.0.1:9/v1",
        temperature=0.3, max_tokens=100, timeout=10, extra_headers={},
        enabled=True, api_key="k",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class _OkStream:
    """正常流式：两个增量 + usage。"""

    def __init__(self, provider, delay=0.0, n_delta=0):
        self._provider = provider
        self._delay = delay
        self._n = n_delta

    def chat_stream(self, messages):
        time.sleep(self._delay)
        yield {"type": "delta", "text": "## 结论\n"}
        for _ in range(self._n):
            yield {"type": "delta", "text": "增量"}
            time.sleep(0.002)
        yield {"type": "usage", "prompt_tokens": 12, "completion_tokens": 34}

    def chat(self, messages):
        raise AssertionError("正常流式不应回退非流式")


class _BrokenThenFallback:
    """流式中断（已吐半截）→ 非流式回退全量。"""

    def chat_stream(self, messages):
        yield {"type": "delta", "text": "半截结果"}
        raise LLMError("流中断", kind="stream_broken")

    def chat(self, messages):
        return SimpleNamespace(
            content="完整结果A" * 200, prompt_tokens=1, completion_tokens=2
        )


class _AuthFail:
    """鉴权失败：不得回退非流式。"""

    def chat_stream(self, messages):
        raise LLMError("401 unauthorized", kind="auth")

    def chat(self, messages):
        raise AssertionError("鉴权失败不应回退非流式")


class _SlowStream:
    """慢速流式：供取消路径使用。"""

    def chat_stream(self, messages):
        while True:
            time.sleep(0.02)
            yield {"type": "delta", "text": "x"}

    def chat(self, messages):
        raise AssertionError("不应回退")


class _EmptyStream:
    """仅 usage 无内容。"""

    def chat_stream(self, messages):
        yield {"type": "usage", "prompt_tokens": 1, "completion_tokens": 2}

    def chat(self, messages):
        return SimpleNamespace(content="", prompt_tokens=1, completion_tokens=2)


# ---------------------------------------------------------------- fixtures

@pytest.fixture()
def svc(monkeypatch):
    """每个用例独立单例，并挂载事件收集器。"""
    monkeypatch.setattr(insight, "_service", None)
    service = insight.get_service()
    events = []
    service.set_event_publisher(lambda tid, payload: events.append(payload))
    return service, events


def _wait_terminal(svc, task_id, timeout=15.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        t = svc.get_task(task_id)
        assert t, "任务丢失"
        if t["status"] in ("success", "failed", "cancelled"):
            return t
        time.sleep(0.02)
    raise AssertionError(f"任务 {timeout}s 未终结: {svc.get_task(task_id)}")


# ---------------------------------------------------------------- 引擎语义

def test_success_streaming_content_tokens_and_events(svc, monkeypatch):
    s, events = svc
    monkeypatch.setattr(insight, "cfg", SimpleNamespace(
        get_default_provider=lambda: _provider(),
        get_provider=lambda pid: _provider(),
    ))
    monkeypatch.setattr(insight, "build_client", lambda p: _OkStream(p, n_delta=5))

    res = s.submit(
        messages=[{"role": "user", "content": "数据"}],
        kind="limitup", title="t", cache_key="k:1", meta={"date": "2026-09-02"},
    )
    assert res["ok"], res
    task = _wait_terminal(s, res["task_id"])
    assert task["status"] == "success"
    assert task["content"].startswith("## 结论")
    assert "增量" in task["content"]
    assert task["prompt_tokens"] == 12 and task["completion_tokens"] == 34
    assert task["model"] == "stub-model"
    assert task["meta"] == {"date": "2026-09-02"}

    kinds = [e.get("event") for e in events]
    assert kinds.count("delta") == 6  # 2 固定增量 + 5 桩增量
    assert "done" in kinds
    done = next(e for e in events if e.get("event") == "done")
    assert done["status"] == "success"


def test_cache_hit_returns_full_content_and_refresh_bypasses(svc, monkeypatch):
    s, _ = svc
    monkeypatch.setattr(insight, "cfg", SimpleNamespace(
        get_default_provider=lambda: _provider(),
        get_provider=lambda pid: _provider(),
    ))
    monkeypatch.setattr(insight, "build_client", lambda p: _OkStream(p))

    r1 = s.submit(messages=[{"role": "user", "content": "d"}], kind="k",
                  cache_key="limitup:2026-09-02")
    _wait_terminal(s, r1["task_id"])

    # 二次提交 → 缓存命中，带完整内容
    r2 = s.submit(messages=[{"role": "user", "content": "d"}], kind="k",
                  cache_key="limitup:2026-09-02")
    assert r2["ok"] and r2["cached"] is True
    assert (r2["task"]["content"] or "").startswith("## 结论")
    assert r2["task"]["status"] == "success"

    # refresh=True → 绕过缓存新建任务
    r3 = s.submit(messages=[{"role": "user", "content": "d"}], kind="k",
                  cache_key="limitup:2026-09-02", refresh=True)
    assert r3["ok"] and not r3["cached"]
    assert r3["task_id"] != r2["task_id"]
    _wait_terminal(s, r3["task_id"])


def test_missing_default_provider_returns_conflict(svc, monkeypatch):
    s, _ = svc
    monkeypatch.setattr(insight, "cfg", SimpleNamespace(
        get_default_provider=lambda: None,
        get_provider=lambda pid: None,
    ))
    res = s.submit(messages=[{"role": "user", "content": "d"}])
    assert res["ok"] is False
    assert res["error"]


def test_auth_error_marks_failed_without_fallback(svc, monkeypatch):
    s, events = svc
    monkeypatch.setattr(insight, "cfg", SimpleNamespace(
        get_default_provider=lambda: _provider(),
        get_provider=lambda pid: _provider(),
    ))
    monkeypatch.setattr(insight, "build_client", lambda p: _AuthFail())

    res = s.submit(messages=[{"role": "user", "content": "d"}], kind="k")
    task = _wait_terminal(s, res["task_id"])
    assert task["status"] == "failed"
    assert task["error_kind"] == "auth"
    done = next(e for e in events if e.get("event") == "done")
    assert done["error_kind"] == "auth"


def test_stream_broken_falls_back_to_non_streaming(svc, monkeypatch):
    s, events = svc
    monkeypatch.setattr(insight, "cfg", SimpleNamespace(
        get_default_provider=lambda: _provider(),
        get_provider=lambda pid: _provider(),
    ))
    monkeypatch.setattr(insight, "build_client", lambda p: _BrokenThenFallback())

    res = s.submit(messages=[{"role": "user", "content": "d"}], kind="k")
    task = _wait_terminal(s, res["task_id"])
    assert task["status"] == "success"
    assert task["content"].startswith("完整结果A")  # 回退后取回的是全量结果
    assert len(task["content"]) > 500


def test_empty_model_output_fails_with_empty_kind(svc, monkeypatch):
    s, _ = svc
    monkeypatch.setattr(insight, "cfg", SimpleNamespace(
        get_default_provider=lambda: _provider(),
        get_provider=lambda pid: _provider(),
    ))
    monkeypatch.setattr(insight, "build_client", lambda p: _EmptyStream())

    res = s.submit(messages=[{"role": "user", "content": "d"}], kind="k")
    task = _wait_terminal(s, res["task_id"])
    assert task["status"] == "failed"
    assert task["error_kind"] == "empty"


def test_cancel_running_task(svc, monkeypatch):
    s, events = svc
    monkeypatch.setattr(insight, "cfg", SimpleNamespace(
        get_default_provider=lambda: _provider(),
        get_provider=lambda pid: _provider(),
    ))
    monkeypatch.setattr(insight, "build_client", lambda p: _SlowStream())

    res = s.submit(messages=[{"role": "user", "content": "d"}], kind="k")
    time.sleep(0.15)  # 等任务进入运行态
    assert s.cancel(res["task_id"]) is True
    task = _wait_terminal(s, res["task_id"])
    assert task["status"] == "cancelled"
    assert any(e.get("event") == "done" and e.get("status") == "cancelled"
               for e in events)
    # 已结束任务不可重复取消
    assert s.cancel(res["task_id"]) is False


# ---------------------------------------------------------------- SSE 回归防护

def _make_router_client() -> TestClient:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(create_router())
    return TestClient(app)


def test_sse_survives_high_frequency_deltas(monkeypatch):
    """回归：高频增量不得掐断 SSE 连接，done 必须到达。

    旧实现把每个事件折算 15s“空闲”，2100s 上限约 140 个事件即触发
    兜底关闭；本用例发布 240 个增量并断言全部/绝大多数可达且收到 done。
    """
    monkeypatch.setattr(insight, "_service", None)
    s = insight.get_service()
    s.set_event_publisher(publish_llm_task_event)

    class _FastStream:
        def __init__(self, provider):
            self._p = provider

        def chat_stream(self, messages):
            time.sleep(0.6)  # 等待 SSE 订阅建立
            for _ in range(240):
                yield {"type": "delta", "text": "片"}
                time.sleep(0.008)
            yield {"type": "usage", "prompt_tokens": 1, "completion_tokens": 2}

        def chat(self, messages):
            raise AssertionError("不应回退")

    monkeypatch.setattr(insight, "cfg", SimpleNamespace(
        get_default_provider=lambda: _provider(name="sse-stub"),
        get_provider=lambda pid: _provider(name="sse-stub"),
    ))
    monkeypatch.setattr(insight, "build_client", lambda p: _FastStream(p))

    res = s.submit(messages=[{"role": "user", "content": "d"}], kind="k")
    assert res["ok"]
    tid = res["task_id"]

    client = _make_router_client()
    names = []
    with client.stream("GET", f"/api/llm/insight/stream?id={tid}") as resp:
        for raw in resp.iter_lines():
            line = (raw or "").strip()
            if line.startswith("event:"):
                ev = line[6:].strip()
                if ev == "done":
                    names.append(ev)
                    break
                names.append(ev)
    assert names.count("delta") > 150, f"高频增量被掐断: 仅收到 {names.count('delta')} 个"
    task = s.get_task(tid)
    assert task["status"] == "success"


def test_sse_late_subscribe_replays_terminal_done(monkeypatch):
    """终态任务的迟到订阅应立即补发 done。"""
    monkeypatch.setattr(insight, "_service", None)
    s = insight.get_service()
    s.set_event_publisher(publish_llm_task_event)

    monkeypatch.setattr(insight, "cfg", SimpleNamespace(
        get_default_provider=lambda: _provider(),
        get_provider=lambda pid: _provider(),
    ))
    monkeypatch.setattr(insight, "build_client", lambda p: _OkStream(p))

    res = s.submit(messages=[{"role": "user", "content": "d"}], kind="k",
                   cache_key="late-sub")
    _wait_terminal(s, res["task_id"])

    client = _make_router_client()
    got = None
    with client.stream("GET", f"/api/llm/insight/stream?id={res['task_id']}") as resp:
        for raw in resp.iter_lines():
            line = (raw or "").strip()
            if line.startswith("event:") and line[6:].strip() == "done":
                got = line[6:].strip()
                break
    assert got == "done"
