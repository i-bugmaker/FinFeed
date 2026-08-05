#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大模型供应商配置管理

支持任意 OpenAI 兼容服务：只需填写 base_url + api_key + model。
配置持久化在主库的 llm_providers 表中。

安全说明：API Key 以明文存储在本地 SQLite（与 FinFeed 其他本地数据同级）。
对外接口一律返回掩码值，不会把完整 Key 回传到前端。
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import now_bj

from .schema import ensure_tables

logger = logging.getLogger("news_monitor")

# ============================================================
# 常见服务预设（仅用于前端一键填充，不含任何密钥）
# ============================================================
PRESETS: List[Dict[str, str]] = [
    {"key": "openai", "label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini"},
    {"key": "deepseek", "label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat"},
    {"key": "dashscope", "label": "阿里通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    {"key": "moonshot", "label": "月之暗面 Kimi", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-32k"},
    {"key": "zhipu", "label": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-plus"},
    {"key": "siliconflow", "label": "硅基流动", "base_url": "https://api.siliconflow.cn/v1", "model": "Qwen/Qwen2.5-32B-Instruct"},
    {"key": "volcengine", "label": "火山方舟豆包", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-pro-32k"},
    {"key": "ollama", "label": "本地 Ollama", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5:14b"},
    {"key": "lmstudio", "label": "本地 LM Studio", "base_url": "http://127.0.0.1:1234/v1", "model": "local-model"},
    {"key": "custom", "label": "自定义", "base_url": "", "model": ""},
]

MASK_PLACEHOLDER = "********"

_FIELDS = (
    "id", "name", "base_url", "api_key", "model", "temperature", "max_tokens",
    "timeout", "extra_headers", "preset", "is_default", "enabled",
    "test_status", "test_message", "test_latency", "test_ts",
    "created_at", "updated_at",
)


@dataclass
class LLMProvider:
    """大模型供应商配置"""
    name: str
    base_url: str
    model: str = ""
    api_key: str = ""
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: int = 120
    extra_headers: Dict[str, str] = field(default_factory=dict)
    preset: str = "custom"
    is_default: bool = False
    enabled: bool = True
    id: Optional[int] = None
    test_status: int = -1          # -1 未测试 / 0 失败 / 1 成功
    test_message: str = ""
    test_latency: float = 0.0
    test_ts: int = 0
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self, mask_key: bool = True) -> Dict[str, Any]:
        d = asdict(self)
        if mask_key:
            key = d.pop("api_key", "") or ""
            d["has_api_key"] = bool(key)
            d["api_key_masked"] = _mask(key)
        return d


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return MASK_PLACEHOLDER
    return f"{key[:4]}{MASK_PLACEHOLDER}{key[-4:]}"


def _row_to_provider(row) -> LLMProvider:
    try:
        headers = json.loads(row["extra_headers"] or "{}")
        if not isinstance(headers, dict):
            headers = {}
    except Exception:
        headers = {}
    return LLMProvider(
        id=row["id"],
        name=row["name"],
        base_url=row["base_url"],
        api_key=row["api_key"] or "",
        model=row["model"] or "",
        temperature=float(row["temperature"] or 0.3),
        max_tokens=int(row["max_tokens"] or 4096),
        timeout=int(row["timeout"] or 120),
        extra_headers=headers,
        preset=row["preset"] or "custom",
        is_default=bool(row["is_default"]),
        enabled=bool(row["enabled"]),
        test_status=int(row["test_status"] if row["test_status"] is not None else -1),
        test_message=row["test_message"] or "",
        test_latency=float(row["test_latency"] or 0),
        test_ts=int(row["test_ts"] or 0),
        created_at=row["created_at"] or "",
        updated_at=row["updated_at"] or "",
    )


# ============================================================
# 查询
# ============================================================
def list_providers() -> List[LLMProvider]:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT * FROM llm_providers ORDER BY is_default DESC, id ASC"
        )
        return [_row_to_provider(r) for r in c.fetchall()]


def get_provider(provider_id: int) -> Optional[LLMProvider]:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT * FROM llm_providers WHERE id = ?", (provider_id,))
        row = c.fetchone()
        return _row_to_provider(row) if row else None


def get_provider_by_name(name: str) -> Optional[LLMProvider]:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT * FROM llm_providers WHERE name = ?", (name,))
        row = c.fetchone()
        return _row_to_provider(row) if row else None


def get_default_provider() -> Optional[LLMProvider]:
    """取默认供应商；无默认时取第一个启用的"""
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "SELECT * FROM llm_providers WHERE is_default = 1 AND enabled = 1 LIMIT 1"
        )
        row = c.fetchone()
        if row:
            return _row_to_provider(row)
        c.execute("SELECT * FROM llm_providers WHERE enabled = 1 ORDER BY id ASC LIMIT 1")
        row = c.fetchone()
        return _row_to_provider(row) if row else None


# ============================================================
# 写入
# ============================================================
def save_provider(data: Dict[str, Any]) -> LLMProvider:
    """新增或更新供应商配置

    api_key 规则：
      - 传入非空且不等于掩码 -> 覆盖
      - 传入空字符串或掩码值 -> 保留原值（更新场景）
    """
    ensure_tables()
    name = (data.get("name") or "").strip()
    base_url = (data.get("base_url") or "").strip()
    model = (data.get("model") or "").strip()
    if not name:
        raise ValueError("配置名称不能为空")
    if not base_url:
        raise ValueError("接口地址（Base URL）不能为空")
    if not model:
        raise ValueError("模型名称不能为空")

    provider_id = data.get("id")
    try:
        provider_id = int(provider_id) if provider_id not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        provider_id = None

    old: Optional[LLMProvider] = get_provider(provider_id) if provider_id else None
    if old is None and provider_id:
        raise ValueError(f"配置 id={provider_id} 不存在")

    dup = get_provider_by_name(name)
    if dup and (old is None or dup.id != old.id):
        raise ValueError(f"配置名称「{name}」已存在")

    api_key = (data.get("api_key") or "").strip()
    if not api_key or MASK_PLACEHOLDER in api_key:
        api_key = old.api_key if old else ""

    headers = data.get("extra_headers") or {}
    if isinstance(headers, str):
        try:
            headers = json.loads(headers) if headers.strip() else {}
        except Exception:
            raise ValueError("额外请求头必须是合法 JSON 对象")
    if not isinstance(headers, dict):
        headers = {}

    def _num(key, cast, default, lo=None, hi=None):
        try:
            v = cast(data.get(key, default))
        except (TypeError, ValueError):
            v = default
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        return v

    temperature = _num("temperature", float, 0.3, 0.0, 2.0)
    max_tokens = _num("max_tokens", int, 4096, 256, 131072)
    timeout = _num("timeout", int, 120, 5, 900)
    preset = (data.get("preset") or "custom").strip() or "custom"
    enabled = 1 if data.get("enabled", True) else 0
    is_default = 1 if data.get("is_default", False) else 0
    ts_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")

    db = get_db_manager()
    with db.get_db() as c:
        if old:
            c.execute(
                """UPDATE llm_providers SET
                       name=?, base_url=?, api_key=?, model=?, temperature=?,
                       max_tokens=?, timeout=?, extra_headers=?, preset=?,
                       enabled=?, updated_at=?
                   WHERE id=?""",
                (name, base_url, api_key, model, temperature, max_tokens, timeout,
                 json.dumps(headers, ensure_ascii=False), preset, enabled, ts_str, old.id),
            )
            new_id = old.id
        else:
            c.execute(
                """INSERT INTO llm_providers
                   (name, base_url, api_key, model, temperature, max_tokens, timeout,
                    extra_headers, preset, is_default, enabled, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, base_url, api_key, model, temperature, max_tokens, timeout,
                 json.dumps(headers, ensure_ascii=False), preset, 0, enabled, ts_str, ts_str),
            )
            new_id = c.lastrowid

        c.execute("SELECT COUNT(*) AS cnt FROM llm_providers")
        total = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) AS cnt FROM llm_providers WHERE is_default = 1")
        has_default = c.fetchone()["cnt"]

        if is_default or total == 1 or not has_default:
            c.execute("UPDATE llm_providers SET is_default = 0")
            c.execute("UPDATE llm_providers SET is_default = 1 WHERE id = ?", (new_id,))

    logger.info(f"LLM 供应商配置已保存: {name} (id={new_id})")
    result = get_provider(new_id)
    assert result is not None
    return result


def delete_provider(provider_id: int) -> bool:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT is_default FROM llm_providers WHERE id = ?", (provider_id,))
        row = c.fetchone()
        if not row:
            return False
        was_default = bool(row["is_default"])
        c.execute("DELETE FROM llm_providers WHERE id = ?", (provider_id,))
        if was_default:
            c.execute("SELECT id FROM llm_providers ORDER BY id ASC LIMIT 1")
            nxt = c.fetchone()
            if nxt:
                c.execute("UPDATE llm_providers SET is_default = 1 WHERE id = ?", (nxt["id"],))
    logger.info(f"LLM 供应商配置已删除: id={provider_id}")
    return True


def set_default_provider(provider_id: int) -> bool:
    ensure_tables()
    db = get_db_manager()
    with db.get_db() as c:
        c.execute("SELECT id FROM llm_providers WHERE id = ?", (provider_id,))
        if not c.fetchone():
            return False
        c.execute("UPDATE llm_providers SET is_default = 0")
        c.execute("UPDATE llm_providers SET is_default = 1, enabled = 1 WHERE id = ?", (provider_id,))
    return True


def update_test_result(provider_id: int, ok: bool, message: str, latency: float = 0.0) -> None:
    """记录一次连通性检测结果"""
    ensure_tables()
    import time as _time
    db = get_db_manager()
    with db.get_db() as c:
        c.execute(
            "UPDATE llm_providers SET test_status=?, test_message=?, test_latency=?, test_ts=? WHERE id=?",
            (1 if ok else 0, message[:500], round(latency, 1), int(_time.time()), provider_id),
        )


def provider_from_payload(data: Dict[str, Any]) -> LLMProvider:
    """把前端表单（未落库）转成临时 Provider，用于「先测后存」

    api_key 为空或掩码时，若携带 id 则回填已存库中的真实 Key。
    """
    api_key = (data.get("api_key") or "").strip()
    pid = data.get("id")
    if (not api_key or MASK_PLACEHOLDER in api_key) and pid:
        try:
            old = get_provider(int(pid))
            if old:
                api_key = old.api_key
        except (TypeError, ValueError):
            pass

    headers = data.get("extra_headers") or {}
    if isinstance(headers, str):
        try:
            headers = json.loads(headers) if headers.strip() else {}
        except Exception:
            headers = {}
    if not isinstance(headers, dict):
        headers = {}

    def _f(key, cast, default):
        try:
            return cast(data.get(key, default))
        except (TypeError, ValueError):
            return default

    return LLMProvider(
        id=int(pid) if pid else None,
        name=(data.get("name") or "临时配置").strip(),
        base_url=(data.get("base_url") or "").strip(),
        model=(data.get("model") or "").strip(),
        api_key=api_key,
        temperature=_f("temperature", float, 0.3),
        max_tokens=_f("max_tokens", int, 4096),
        timeout=_f("timeout", int, 120),
        extra_headers=headers,
        preset=(data.get("preset") or "custom").strip(),
    )
