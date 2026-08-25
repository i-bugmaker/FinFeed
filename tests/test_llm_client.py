#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 客户端单元测试：URL 归一化 / 流式解析 / token 估算。

chat_stream 通过 httpx.MockTransport 模拟 OpenAI SSE chunk 协议，
不发起真实网络请求。
"""

import json

import httpx
import pytest
from finfeed.llm.client import (
    LLMClient,
    LLMError,
    build_chat_url,
    build_models_url,
    estimate_tokens,
)


# ============================================================
# URL 归一化（回归保护：用户配置容错的关键路径）
# ============================================================
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://api.x.com", "https://api.x.com/v1/chat/completions"),
        ("https://api.x.com/", "https://api.x.com/v1/chat/completions"),
        ("https://api.x.com/v1", "https://api.x.com/v1/chat/completions"),
        (
            "https://api.x.com/v1/chat/completions",
            "https://api.x.com/v1/chat/completions",
        ),
        ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions"),
    ],
)
def test_build_chat_url_normalizes_common_inputs(raw, expected):
    assert build_chat_url(raw) == expected


def test_build_models_url_appends_models_endpoint():
    assert build_models_url("https://api.x.com") == "https://api.x.com/v1/models"
    assert build_models_url("https://api.x.com/v1") == "https://api.x.com/v1/models"


def test_estimate_tokens_positive_floor():
    assert estimate_tokens("") >= 1
    assert estimate_tokens("一二三四五六七八九十") == 5


# ============================================================
# chat_stream：SSE 解析
# ============================================================
def _sse_body(chunks, done=True):
    lines = [f"data: {json.dumps(c)}" for c in chunks]
    if done:
        lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode("utf-8")


def _run_stream(client, payload_chunks, *, status=200, break_after=None):
    """驱动 chat_stream 消费 mock 响应，返回事件列表。"""
    events = []

    def make_body():
        if break_after is None:
            return iter([_sse_body(payload_chunks)])
        first = _sse_body(payload_chunks[:break_after], done=False)
        return _Interrupted(first)

    def handler(request):
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "bad key"}})
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=make_body(),
        )

    real_httpx_client_init = httpx.Client

    def fake_client_init(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_httpx_client_init(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkey_target = "finfeed.llm.client.httpx.Client"
    import unittest.mock as mock

    with mock.patch(monkey_target, side_effect=fake_client_init):
        for ev in client.chat_stream(
            [{"role": "user", "content": "hi"}], max_tokens=64
        ):
            events.append(ev)
    return events


class _Interrupted:
    """先输出前半段，随后模拟连接中断。"""

    def __init__(self, first):
        self._it = iter([first])

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise httpx.ReadError("connection reset") from None


def test_chat_stream_parses_deltas_and_usage():
    chunks = [
        {"choices": [{"delta": {"content": "# 报告"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "\n正文"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": "stop"}],
         "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}},
    ]
    events = _run_stream(LLMClient(base_url="https://api.test/v1", model="m"), chunks)

    deltas = [e["text"] for e in events if e["type"] == "delta"]
    usage = [e for e in events if e["type"] == "usage"]
    assert "".join(deltas) == "# 报告\n正文"
    assert usage and usage[0]["prompt_tokens"] == 11 and usage[0]["completion_tokens"] == 7


def test_chat_stream_skips_reasoning_content():
    """思考型模型的 reasoning_content 不得混入报告正文。"""
    chunks = [
        {"choices": [{"delta": {"reasoning_content": "让我想想…"}}]},
        {"choices": [{"delta": {"content": "结论"}}]},
    ]
    events = _run_stream(LLMClient(base_url="https://api.test/v1", model="m"), chunks)
    deltas = [e["text"] for e in events if e["type"] == "delta"]
    assert deltas == ["结论"]


def test_chat_stream_auth_error_before_first_byte():
    with pytest.raises(LLMError) as ei:
        _run_stream(
            LLMClient(base_url="https://api.test/v1", model="m"),
            [],
            status=401,
        )
    assert ei.value.kind == "auth"


def test_chat_stream_broken_midway_raises_stream_broken():
    chunks = [
        {"choices": [{"delta": {"content": "前半段"}}]},
        {"choices": [{"delta": {"content": "后半段"}}]},
    ]
    with pytest.raises(LLMError) as ei:
        _run_stream(
            LLMClient(base_url="https://api.test/v1", model="m"),
            chunks,
            break_after=1,
        )
    assert ei.value.kind == "stream_broken"


# ============================================================
# service：事件发布器注入
# ============================================================
def test_service_publishes_and_swallows_publisher_errors():
    from finfeed.llm.service import AnalysisService

    svc = AnalysisService()
    seen = []
    svc.set_event_publisher(lambda tid, payload: seen.append((tid, payload)))

    svc._publish("t1", event="delta", text="x")
    assert seen == [("t1", {"task_id": "t1", "event": "delta", "text": "x"})]

    def boom(task_id, payload):
        raise RuntimeError("subscriber down")

    svc.set_event_publisher(boom)
    svc._publish("t1", event="delta", text="y")  # 不应抛出

    svc.set_event_publisher(None)
    svc._publish("t1", event="delta", text="z")
    assert len(seen) == 1
