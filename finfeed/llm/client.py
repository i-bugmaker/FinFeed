#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAI 兼容大模型客户端

覆盖绝大多数主流服务：OpenAI / DeepSeek / 通义千问兼容模式 / Kimi / 智谱 /
硅基流动 / 火山方舟 / Ollama / LM Studio / vLLM / OneAPI 等。

设计要点：
  - 同步实现（在独立工作线程中调用，不侵入主 asyncio 事件循环）
  - URL 智能归一化：裸域名、带 /v1、完整 /chat/completions 端点均可
  - 分级错误诊断：DNS / 连接 / 超时 / 鉴权 / 限流 / 服务端错误分别给出可读结论
  - 连通性检测三步走：端点探测 -> 模型列表 -> 最小对话
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("news_monitor")

DEFAULT_TEST_TIMEOUT = 20.0
_RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


def estimate_tokens(text: str) -> int:
    """按字数粗估 token 数（中文场景约 2 字符 / token）。

    仅用于流式响应缺少 usage 时的近似统计；报告页脚本就标注「token 约」。
    """
    return max(1, round(len(text or "") / 2))


class LLMError(Exception):
    """LLM 调用异常（携带可读诊断）"""

    def __init__(self, message: str, *, kind: str = "unknown", status: int = 0, detail: str = ""):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.status = status
        self.detail = detail

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "kind": self.kind,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class ChatResult:
    content: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency: float = 0.0
    model: str = ""
    finish_reason: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


# URL 归一化
def normalize_base(url: str) -> str:
    """去掉尾部斜杠与显式端点后缀，得到 base"""
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    for suffix in ("/chat/completions", "/completions"):
        if u.endswith(suffix):
            u = u[: -len(suffix)]
            break
    return u.rstrip("/")


def build_chat_url(url: str) -> str:
    """推导 chat/completions 完整端点

    规则：
      https://api.x.com                 -> https://api.x.com/v1/chat/completions
      https://api.x.com/v1              -> https://api.x.com/v1/chat/completions
      https://api.x.com/v1/chat/completions（原样使用）
      http://127.0.0.1:11434/v1         -> http://127.0.0.1:11434/v1/chat/completions
    """
    raw = (url or "").strip().rstrip("/")
    if raw.endswith("/chat/completions"):
        return raw
    base = normalize_base(raw)
    if not base:
        return ""
    path = urlparse(base).path.rstrip("/")
    if not path:
        base = f"{base}/v1"
    return f"{base}/chat/completions"


def build_models_url(url: str) -> str:
    """推导 models 列表端点"""
    raw = (url or "").strip().rstrip("/")
    if raw.endswith("/chat/completions"):
        base = raw[: -len("/chat/completions")]
    else:
        base = normalize_base(raw)
        if base and not urlparse(base).path.rstrip("/"):
            base = f"{base}/v1"
    return f"{base}/models" if base else ""


def validate_url(url: str) -> Optional[str]:
    """返回错误说明，None 表示合法"""
    u = (url or "").strip()
    if not u:
        return "接口地址不能为空"
    if not u.startswith(("http://", "https://")):
        return "接口地址必须以 http:// 或 https:// 开头"
    parsed = urlparse(u)
    if not parsed.netloc:
        return "接口地址缺少主机名"
    return None


# 客户端
class LLMClient:
    """OpenAI 兼容的最小可用客户端"""

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
        timeout: int = 120,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self.base_url = base_url
        self.api_key = api_key or ""
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    # ---------- 内部 ----------
    def _headers(self) -> Dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "FinFeed-LLM/1.0",
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        for k, v in (self.extra_headers or {}).items():
            if k and v:
                h[str(k)] = str(v)
        return h

    @staticmethod
    def _classify_transport_error(e: Exception) -> LLMError:
        if isinstance(e, httpx.ConnectTimeout):
            return LLMError(
                "连接超时：无法在限定时间内建立连接，请检查地址、端口与网络代理", kind="timeout"
            )
        if isinstance(e, httpx.ReadTimeout):
            return LLMError(
                "读取超时：服务端未在超时时间内返回，建议调大超时或减小单次输入", kind="timeout"
            )
        if isinstance(e, httpx.ConnectError):
            msg = str(e)
            if "getaddrinfo" in msg or "Name or service not known" in msg or "nodename" in msg:
                return LLMError(
                    "域名解析失败：主机名不存在或 DNS 不可达", kind="dns", detail=msg[:300]
                )
            if "Connection refused" in msg or "10061" in msg:
                return LLMError(
                    "连接被拒绝：目标端口未监听（本地模型服务是否已启动？）",
                    kind="refused",
                    detail=msg[:300],
                )
            if "certificate" in msg.lower() or "ssl" in msg.lower():
                return LLMError("TLS/SSL 握手失败：证书校验不通过", kind="tls", detail=msg[:300])
            return LLMError(f"网络连接失败：{msg[:160]}", kind="network", detail=msg[:300])
        if isinstance(e, httpx.TimeoutException):
            return LLMError("请求超时", kind="timeout", detail=str(e)[:300])
        if isinstance(e, httpx.ProxyError):
            return LLMError("代理错误：请检查系统代理设置", kind="proxy", detail=str(e)[:300])
        return LLMError(
            f"请求异常：{type(e).__name__}: {str(e)[:160]}", kind="unknown", detail=str(e)[:300]
        )

    @staticmethod
    def _classify_http_status(status: int, body_text: str) -> LLMError:
        snippet = (body_text or "")[:400]
        api_msg = ""
        try:
            data = json.loads(body_text)
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    api_msg = err.get("message") or ""
                elif isinstance(err, str):
                    api_msg = err
                api_msg = api_msg or data.get("message") or ""
        except Exception:
            pass
        tail = f"（服务端提示：{api_msg[:200]}）" if api_msg else ""

        if status == 401:
            return LLMError(
                f"鉴权失败 401：API Key 无效或未被接受{tail}",
                kind="auth",
                status=status,
                detail=snippet,
            )
        if status == 403:
            return LLMError(
                f"访问被拒 403：Key 无该模型权限或来源受限{tail}",
                kind="auth",
                status=status,
                detail=snippet,
            )
        if status == 404:
            return LLMError(
                f"端点不存在 404：Base URL 路径可能不对（是否缺少 /v1），或模型名不存在{tail}",
                kind="endpoint",
                status=status,
                detail=snippet,
            )
        if status == 422 or status == 400:
            return LLMError(
                f"请求参数不被接受 {status}{tail}", kind="param", status=status, detail=snippet
            )
        if status == 429:
            return LLMError(
                f"触发限流 429：请求过于频繁或余额/配额不足{tail}",
                kind="ratelimit",
                status=status,
                detail=snippet,
            )
        if 500 <= status < 600:
            return LLMError(
                f"服务端错误 {status}{tail}", kind="server", status=status, detail=snippet
            )
        return LLMError(f"HTTP {status} 异常响应{tail}", kind="http", status=status, detail=snippet)

    # ---------- 公开方法 ----------
    def list_models(self, timeout: Optional[float] = None) -> Tuple[bool, List[str], str]:
        """拉取模型列表。返回 (是否成功, 模型名列表, 说明)"""
        url = build_models_url(self.base_url)
        if not url:
            return False, [], "无法推导模型列表端点"
        try:
            with httpx.Client(
                timeout=timeout or DEFAULT_TEST_TIMEOUT, follow_redirects=True
            ) as client:
                resp = client.get(url, headers=self._headers())
            if resp.status_code != 200:
                return False, [], f"HTTP {resp.status_code}"
            data = resp.json()
            items = data.get("data") if isinstance(data, dict) else None
            if not isinstance(items, list):
                items = data if isinstance(data, list) else []
            names = []
            for it in items:
                if isinstance(it, dict):
                    mid = it.get("id") or it.get("name") or it.get("model")
                    if mid:
                        names.append(str(mid))
                elif isinstance(it, str):
                    names.append(it)
            return True, names, "ok"
        except Exception as e:
            return False, [], f"{type(e).__name__}: {str(e)[:120]}"

    def chat(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        retries: int = 2,
    ) -> ChatResult:
        """发起一次对话补全"""
        url = build_chat_url(self.base_url)
        if not url:
            raise LLMError("接口地址无效", kind="param")
        if not self.model:
            raise LLMError("未指定模型名称", kind="param")

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        req_timeout = float(timeout or self.timeout)

        last_err: Optional[LLMError] = None
        for attempt in range(retries + 1):
            t0 = time.time()
            try:
                with httpx.Client(timeout=req_timeout, follow_redirects=True) as client:
                    resp = client.post(url, headers=self._headers(), json=payload)
                latency = (time.time() - t0) * 1000

                if resp.status_code != 200:
                    err = self._classify_http_status(resp.status_code, resp.text)
                    if resp.status_code in _RETRYABLE_STATUS and attempt < retries:
                        last_err = err
                        time.sleep(min(2**attempt, 5))
                        continue
                    raise err

                try:
                    data = resp.json()
                except Exception:
                    raise LLMError(
                        "响应不是合法 JSON，目标可能不是 OpenAI 兼容接口",
                        kind="protocol",
                        detail=resp.text[:300],
                    )

                content, finish = _extract_content(data)
                if not content:
                    raise LLMError(
                        "模型返回内容为空",
                        kind="empty",
                        detail=json.dumps(data, ensure_ascii=False)[:300],
                    )

                usage = data.get("usage") or {}
                return ChatResult(
                    content=content,
                    prompt_tokens=int(usage.get("prompt_tokens") or 0),
                    completion_tokens=int(usage.get("completion_tokens") or 0),
                    total_tokens=int(usage.get("total_tokens") or 0),
                    latency=latency,
                    model=str(data.get("model") or self.model),
                    finish_reason=finish,
                    raw=data if len(str(data)) < 20000 else {},
                )
            except LLMError:
                raise
            except Exception as e:
                err = self._classify_transport_error(e)
                if err.kind in ("timeout", "network", "server") and attempt < retries:
                    last_err = err
                    time.sleep(min(2**attempt, 5))
                    continue
                raise err

        raise last_err or LLMError("调用失败", kind="unknown")

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> Iterator[Dict[str, Any]]:
        """流式对话补全（OpenAI SSE chunk 协议）。

        产出事件：
          {"type": "delta", "text": str}   —— 正文增量（可能为空串，调用方需容忍）
          {"type": "usage", "prompt_tokens": int, "completion_tokens": int}
                                           —— 终止前若服务端携带 usage 则产出一次

        错误语义：
          - 首字节之前失败（连接/鉴权/参数）-> 抛 LLMError，调用方可安全回退非流式；
          - 已输出增量后流中断           -> 抛 LLMError(kind="stream_broken")，
            此时增量已不可信，调用方同样应回退非流式重取完整结果。
        """
        url = build_chat_url(self.base_url)
        if not url:
            raise LLMError("接口地址无效", kind="param")
        if not self.model:
            raise LLMError("未指定模型名称", kind="param")

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": True,
        }

        emitted = False
        try:
            with httpx.Client(
                timeout=float(timeout or self.timeout), follow_redirects=True
            ) as client:
                with client.stream("POST", url, headers=self._headers(), json=payload) as resp:
                    if resp.status_code != 200:
                        body_text = resp.read().decode("utf-8", errors="replace")
                        raise self._classify_http_status(resp.status_code, body_text)

                    for line in resp.iter_lines():
                        line = (line or "").strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except Exception:
                            continue
                        if not isinstance(chunk, dict):
                            continue

                        usage = chunk.get("usage")
                        if isinstance(usage, dict) and (
                            usage.get("total_tokens") or usage.get("completion_tokens")
                        ):
                            yield {
                                "type": "usage",
                                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                                "completion_tokens": int(usage.get("completion_tokens") or 0),
                            }

                        choices = chunk.get("choices")
                        if not isinstance(choices, list) or not choices:
                            continue
                        delta = (choices[0] or {}).get("delta") or {}
                        piece = ""
                        if isinstance(delta, dict):
                            content = delta.get("content")
                            if isinstance(content, str):
                                piece = content
                            elif isinstance(content, list):
                                piece = "".join(
                                    seg.get("text", "") if isinstance(seg, dict) else str(seg)
                                    for seg in content
                                )
                            # 注意：思考型模型（如 DeepSeek-R1）的 reasoning_content
                            # 刻意不采集——流式正文将作为报告权威内容，混入思考文本会污染结果。
                        text_field = (choices[0] or {}).get("text")
                        if not piece and isinstance(text_field, str):
                            piece = text_field
                        if piece:
                            emitted = True
                            yield {"type": "delta", "text": piece}
        except LLMError:
            raise
        except Exception as e:
            err = self._classify_transport_error(e)
            if emitted:
                raise LLMError(
                    f"流式输出中断：{err.message}",
                    kind="stream_broken",
                    detail=err.detail,
                ) from e
            raise err

    def test_connection(self) -> Dict[str, Any]:
        """连通性检测：地址校验 -> 模型列表 -> 最小对话

        返回结构化诊断，前端可直接展示。
        """
        result: Dict[str, Any] = {
            "ok": False,
            "chat_url": build_chat_url(self.base_url),
            "models_url": build_models_url(self.base_url),
            "steps": [],
            "models": [],
            "model_listed": None,
            "latency_ms": 0.0,
            "reply": "",
            "message": "",
            "kind": "",
        }

        def step(name: str, ok: bool, msg: str, extra: Optional[Dict[str, Any]] = None):
            item = {"name": name, "ok": ok, "message": msg}
            if extra:
                item.update(extra)
            result["steps"].append(item)

        url_err = validate_url(self.base_url)
        if url_err:
            step("地址校验", False, url_err)
            result["message"] = url_err
            result["kind"] = "param"
            return result
        step("地址校验", True, f"目标端点 {result['chat_url']}")

        if not self.model:
            step("模型检查", False, "未填写模型名称")
            result["message"] = "未填写模型名称"
            result["kind"] = "param"
            return result

        ok_models, names, note = self.list_models(
            timeout=min(float(self.timeout), DEFAULT_TEST_TIMEOUT)
        )
        if ok_models:
            result["models"] = names[:200]
            listed = self.model in names
            result["model_listed"] = listed
            step(
                "模型列表",
                True,
                f"返回 {len(names)} 个模型；目标模型 {'已在列表中' if listed else '不在列表中（部分服务不暴露全部模型，可忽略）'}",
            )
        else:
            step(
                "模型列表",
                False,
                f"未能拉取模型列表（{note}），部分服务不提供该端点，继续进行对话测试",
            )

        t0 = time.time()
        try:
            res = self.chat(
                [
                    {"role": "system", "content": "你是连通性测试探针，只输出要求的内容。"},
                    {"role": "user", "content": "仅回复两个字：正常"},
                ],
                max_tokens=16,
                temperature=0,
                timeout=min(float(self.timeout), 60.0),
                retries=0,
            )
            latency = (time.time() - t0) * 1000
            result["ok"] = True
            result["latency_ms"] = round(latency, 1)
            result["reply"] = res.content.strip()[:100]
            result["message"] = f"连通正常，往返 {round(latency)} ms，模型回复「{result['reply']}」"
            step(
                "对话测试",
                True,
                result["message"],
                {"prompt_tokens": res.prompt_tokens, "completion_tokens": res.completion_tokens},
            )
        except LLMError as e:
            result["ok"] = False
            result["message"] = e.message
            result["kind"] = e.kind
            step("对话测试", False, e.message, {"detail": e.detail, "status": e.status})
        except Exception as e:
            result["ok"] = False
            result["message"] = f"未预期异常：{type(e).__name__}: {str(e)[:160]}"
            result["kind"] = "unknown"
            step("对话测试", False, result["message"])

        return result


def _extract_content(data: Dict[str, Any]) -> Tuple[str, str]:
    """从多种响应结构中提取正文"""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        ch = choices[0] or {}
        finish = str(ch.get("finish_reason") or "")
        msg = ch.get("message") or {}
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, list):  # 部分服务返回分段结构
                content = "".join(
                    seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in content
                )
            if content:
                return str(content).strip(), finish
            reasoning = msg.get("reasoning_content")
            if reasoning:
                return str(reasoning).strip(), finish
        if ch.get("text"):
            return str(ch["text"]).strip(), finish
    if isinstance(data.get("output"), dict):
        text = data["output"].get("text")
        if text:
            return str(text).strip(), ""
    return "", ""


def build_client(provider) -> LLMClient:
    """由 LLMProvider 构造客户端"""
    return LLMClient(
        base_url=provider.base_url,
        api_key=provider.api_key,
        model=provider.model,
        temperature=provider.temperature,
        max_tokens=provider.max_tokens,
        timeout=provider.timeout,
        extra_headers=provider.extra_headers,
    )
