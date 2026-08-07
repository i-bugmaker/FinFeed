#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM 模块 HTTP 接口

被 finfeed/ui/web/server.py 以「前缀路由」方式挂载，模块自洽：
    GET  /api/llm/*   -> handle_get(path, query_dict)
    POST /api/llm/*   -> handle_post(path, json_body)
返回 (status_code, dict)；返回 None 表示该路径不属于本模块。

导出走独立函数 export_report()，由 server 层写响应体。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from finfeed.utils.time_utils import now_bj

from . import collector, config as cfg, store
from .client import LLMClient, LLMError, build_client, build_chat_url, build_models_url
from .schema import ensure_tables
from .service import get_service

logger = logging.getLogger("news_monitor")

Response = Optional[Tuple[int, Dict[str, Any]]]


def _q(qs: Dict[str, List[str]], key: str, default: str = "") -> str:
    v = qs.get(key)
    return v[0] if v else default


def _qi(qs: Dict[str, List[str]], key: str, default: int = 0) -> int:
    try:
        return int(_q(qs, key, str(default)))
    except (TypeError, ValueError):
        return default


def _qf(qs: Dict[str, List[str]], key: str, default: float = 0.0) -> float:
    try:
        return float(_q(qs, key, str(default)))
    except (TypeError, ValueError):
        return default


# ============================================================
# GET
# ============================================================
def handle_get(path: str, qs: Dict[str, List[str]]) -> Response:
    if not path.startswith("/api/llm"):
        return None
    ensure_tables()

    try:
        if path == "/api/llm/status":
            return 200, _status_payload()

        if path == "/api/llm/init":
            # 一次返回首页所需的全部初始化数据，减少视图切换时的往返次数
            return 200, {
                "presets": cfg.PRESETS,
                "scopes": [{"key": k, "label": v} for k, v in collector.SCOPES.items()],
                "windows": list(collector.ALLOWED_WINDOWS),
                "status": _status_payload(),
                "providers": [p.to_dict() for p in cfg.list_providers()],
                "reports": store.list_reports(limit=30, offset=0).get("items", []),
            }

        if path == "/api/llm/presets":
            return 200, {"presets": cfg.PRESETS, "scopes": [
                {"key": k, "label": v} for k, v in collector.SCOPES.items()
            ], "windows": list(collector.ALLOWED_WINDOWS)}

        if path == "/api/llm/prompts":
            from . import prompts as _prompts
            return 200, {
                "defaults": _prompts.DEFAULT_PROMPTS,
                "custom": {
                    k: cfg.get_setting("prompt_" + k, "")
                    for k in _prompts.DEFAULT_PROMPTS
                },
            }

        if path == "/api/llm/providers":
            items = [p.to_dict() for p in cfg.list_providers()]
            return 200, {"providers": items, "count": len(items)}

        if path == "/api/llm/provider":
            p = cfg.get_provider(_qi(qs, "id"))
            if not p:
                return 404, {"error": "配置不存在"}
            return 200, {"provider": p.to_dict()}

        if path == "/api/llm/preview":
            data = collector.preview_window(
                hours=_qi(qs, "hours", 24),
                scope=_q(qs, "scope", collector.SCOPE_ALL),
                min_importance=_qf(qs, "min_importance", 0.0),
            )
            data["estimate"] = _estimate(data["matched"], _qi(qs, "max_items", 500))
            return 200, data

        if path == "/api/llm/task":
            tid = _q(qs, "id")
            task = get_service().get_task(tid) if tid else get_service().get_active()
            if not task:
                return 200, {"task": None}
            payload: Dict[str, Any] = {"task": task}
            if task.get("status") == "success" and task.get("report_id"):
                payload["report"] = store.get_report(task["report_id"])
            return 200, payload

        if path == "/api/llm/tasks":
            return 200, {"tasks": get_service().list_tasks(limit=_qi(qs, "limit", 10))}

        if path == "/api/llm/reports":
            kw = _q(qs, "q", "").strip()
            if kw:
                return 200, store.search_reports(
                    kw, limit=max(1, min(_qi(qs, "limit", 30), 200)))
            return 200, store.list_reports(
                limit=max(1, min(_qi(qs, "limit", 30), 200)),
                offset=max(0, _qi(qs, "offset", 0)),
                pinned_only=_q(qs, "pinned", "0") == "1",
            )

        if path == "/api/llm/report":
            rid = _qi(qs, "id")
            rep = store.get_report(rid)
            if not rep:
                return 404, {"error": "报告不存在"}
            return 200, {"report": rep}

        return 404, {"error": "未知的 LLM 接口"}
    except Exception as e:
        logger.error(f"LLM API GET 异常 {path}: {e}", exc_info=True)
        return 500, {"error": f"{type(e).__name__}: {str(e)[:200]}"}


# ============================================================
# POST
# ============================================================
def handle_post(path: str, data: Dict[str, Any]) -> Response:
    if not path.startswith("/api/llm"):
        return None
    ensure_tables()
    data = data or {}

    try:
        if path == "/api/llm/provider/save":
            try:
                p = cfg.save_provider(data)
            except ValueError as ve:
                return 400, {"error": str(ve)}
            return 200, {"success": True, "provider": p.to_dict()}

        if path == "/api/llm/provider/delete":
            ok = cfg.delete_provider(int(data.get("id", 0)))
            return (200, {"success": True}) if ok else (404, {"error": "配置不存在"})

        if path == "/api/llm/provider/default":
            ok = cfg.set_default_provider(int(data.get("id", 0)))
            return (200, {"success": True}) if ok else (404, {"error": "配置不存在"})

        if path == "/api/llm/provider/test":
            return _handle_test(data)

        if path == "/api/llm/prompts":
            from . import prompts as _prompts
            saved = 0
            for k in _prompts.DEFAULT_PROMPTS:
                v = data.get("prompt_" + k, data.get(k))
                if v is None:
                    continue
                cfg.set_setting("prompt_" + k, "" if not str(v).strip() else str(v))
                saved += 1
            return 200, {"success": True, "saved": saved}

        if path == "/api/llm/analyze":
            result = get_service().submit(data)
            return (200, result) if result.get("ok") else (409, result)

        if path == "/api/llm/task/cancel":
            tid = str(data.get("task_id") or "")
            ok = get_service().cancel(tid)
            return (200, {"success": True}) if ok else (404, {"error": "任务不存在或已结束"})

        if path == "/api/llm/report/delete":
            ok = store.delete_report(int(data.get("id", 0)))
            return (200, {"success": True}) if ok else (404, {"error": "报告不存在"})

        if path == "/api/llm/report/pin":
            rid = int(data.get("id", 0))
            pinned = bool(data.get("pinned", True))
            ok = store.set_pinned(rid, pinned)
            return (200, {"success": True, "pinned": pinned}) if ok else (404, {"error": "报告不存在"})

        if path == "/api/llm/chat":
            return _handle_chat(data)

        if path == "/api/llm/reports/clear":
            n = store.clear_reports()
            return 200, {"success": True, "deleted": n}

        return 404, {"error": "未知的 LLM 接口"}
    except Exception as e:
        logger.error(f"LLM API POST 异常 {path}: {e}", exc_info=True)
        return 500, {"error": f"{type(e).__name__}: {str(e)[:200]}"}


# ============================================================
# 内部
# ============================================================
def _status_payload() -> Dict[str, Any]:
    providers = cfg.list_providers()
    default = cfg.get_default_provider()
    svc = get_service()
    return {
        "provider_count": len(providers),
        "default_provider": default.to_dict() if default else None,
        "busy": svc.is_busy(),
        "active_task": svc.get_active(),
        "server_time": now_bj().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _estimate(matched: int, max_items: int) -> Dict[str, Any]:
    """粗略估算送分析条数、批次数与耗时"""
    max_items = max(20, min(int(max_items or 500), 5000))
    selected = min(matched, max_items)
    approx_chars = selected * 120
    chunks = max(1, -(-approx_chars // 8000))
    chunks = min(chunks, 20)
    calls = 1 if chunks == 1 else chunks + 1
    return {
        "selected": selected,
        "truncated": matched > selected,
        "approx_chars": approx_chars,
        "chunks": chunks,
        "llm_calls": calls,
        "eta_seconds": calls * 12,
    }


def _handle_test(data: Dict[str, Any]) -> Response:
    """连通性检测：支持「已保存配置」与「表单临时配置」两种入参"""
    pid = data.get("id")
    provider = None
    if data.get("use_saved") and pid:
        provider = cfg.get_provider(int(pid))
        if not provider:
            return 404, {"error": "配置不存在"}
    else:
        provider = cfg.provider_from_payload(data)

    if not provider.base_url:
        return 400, {"ok": False, "message": "接口地址不能为空", "steps": []}

    client: LLMClient = build_client(provider)
    result = client.test_connection()
    result["provider_name"] = provider.name
    result["model"] = provider.model
    result["chat_url"] = build_chat_url(provider.base_url)
    result["models_url"] = build_models_url(provider.base_url)

    if provider.id:
        try:
            cfg.update_test_result(
                provider.id, result["ok"], result.get("message", ""),
                result.get("latency_ms", 0.0),
            )
        except Exception as e:
            logger.debug(f"写入检测结果失败: {e}")

    return 200, result


# ============================================================
# 报告追问（针对单份报告的上下文问答）
# ============================================================
def _handle_chat(data: Dict[str, Any]) -> Response:
    """对已生成报告进行追问：以报告正文 + 程序统计为上下文，回答用户问题。

    入参：
      report_id : 报告 ID（必填）
      question  : 用户问题（必填）
      history   : 可选，此前对话 [{role, content}...]，用于多轮追问
    """
    rid = int(data.get("report_id") or 0)
    question = str(data.get("question") or "").strip()
    if rid <= 0:
        return 400, {"ok": False, "error": "缺少报告 ID"}
    if not question:
        return 400, {"ok": False, "error": "请输入问题"}

    rep = store.get_report(rid)
    if not rep:
        return 404, {"ok": False, "error": "报告不存在"}

    provider = cfg.get_default_provider()
    if provider is None:
        return 409, {"ok": False, "error": "尚未配置任何大语言模型"}
    if not provider.enabled:
        return 409, {"ok": False, "error": f"配置「{provider.name}」已被禁用"}

    # 组装上下文：报告元信息 + 正文 + 统计
    stats = rep.get("stats") or {}
    stats_block = ""
    if stats:
        stats_block = "\n".join([
            f"- 样本条数：{stats.get('total', 0)} 条",
            f"- 情绪分布：正面 {stats.get('sentiment', {}).get('positive', 0)} / "
            f"中性 {stats.get('sentiment', {}).get('neutral', 0)} / "
            f"负面 {stats.get('sentiment', {}).get('negative', 0)}",
            f"- 多空比（正/多空）：{stats.get('bull_ratio', '-')}%",
        ])
        if stats.get("top_stocks"):
            stats_block += "\n- 提及最多个股：" + "、".join(
                f"{s['name']}({s['code']}) {s['count']}次"
                for s in stats["top_stocks"][:12]
            )

    body = rep.get("content") or ""
    context = f"""你正在协助用户深入解读一份由 FinFeed 生成的财经复盘报告。请只依据以下材料回答，不要编造数据或材料之外的信息。

【报告信息】
标题：{rep.get('title') or ''}
模型：{rep.get('model') or ''}
时间窗口：{rep.get('window_hours') or 24} 小时，覆盖 {rep.get('news_count') or 0} 条资讯

【程序统计】
{stats_block or '（无）'}

【报告正文】
{body}

用户可能会针对报告中的某个结论、个股、板块、数据或风险点提问。回答要求：
1. 简洁、直接、结构清晰（要点列表优先）；
2. 引用报告内容时注明出处章节；
3. 报告未提及的信息，明确说明"报告中未涉及"，不要自行发挥；
4. 涉及投资判断时给出风险提示。"""

    try:
        client = build_client(provider)
        messages: List[Dict[str, str]] = [{"role": "system", "content": context}]
        history = data.get("history")
        if isinstance(history, list):
            for m in history[-8:]:
                if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
                    messages.append({
                        "role": m["role"],
                        "content": str(m["content"])[:4000],
                    })
        messages.append({"role": "user", "content": question[:4000]})

        res = client.chat(messages, temperature=0.3)
        return 200, {
            "ok": True,
            "reply": res.content.strip(),
            "model": res.model or provider.model,
            "prompt_tokens": res.prompt_tokens,
            "completion_tokens": res.completion_tokens,
        }
    except LLMError as e:
        logger.warning(f"LLM 追问失败: {e.message}")
        return 502, {"ok": False, "error": e.message, "kind": e.kind}
    except Exception as e:
        logger.error(f"LLM 追问异常: {e}", exc_info=True)
        return 500, {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


# ============================================================
# 报告导出
# ============================================================
def export_report(report_id: int, fmt: str = "md") -> Optional[Tuple[str, bytes, str]]:
    """返回 (文件名, 内容字节, Content-Type)"""
    ensure_tables()
    rep = store.get_report(report_id)
    if not rep:
        return None
    ts = (rep.get("created_at") or now_bj().strftime("%Y-%m-%d %H:%M:%S"))
    stamp = ts.replace("-", "").replace(":", "").replace(" ", "_")
    if fmt in ("md", "markdown"):
        return (
            f"finfeed_ai_report_{stamp}.md",
            (rep.get("content") or "").encode("utf-8"),
            "text/markdown; charset=utf-8",
        )
    if fmt == "txt":
        return (
            f"finfeed_ai_report_{stamp}.txt",
            (rep.get("content") or "").encode("utf-8"),
            "text/plain; charset=utf-8",
        )
    import json as _json
    return (
        f"finfeed_ai_report_{stamp}.json",
        _json.dumps(rep, ensure_ascii=False, indent=2).encode("utf-8"),
        "application/json; charset=utf-8",
    )
