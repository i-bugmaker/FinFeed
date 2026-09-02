#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 分析用例服务（应用层，框架无关）

从原 finfeed.llm.api 收敛而来。领域包（finfeed.llm）不感知 HTTP；
本模块只做「取数 + 编排 + 组装 dict」，输入输出均为纯 Python 数据结构，
由 ui.web_fastapi.routers.llm 负责校验与传输映射。

职责：
  - status_payload()   服务状态聚合（供应商 / 默认模型可用性 / 任务忙闲）
  - init_payload()     工作台首屏一次性数据
  - preview_estimate() 送分析量 / 批次 / 耗时预估
  - analysis_defaults()/save_analysis_defaults()  分析默认值（服务端持久化）
  - chat_report()      报告追问（以报告正文 + 统计为上下文）
  - chat_stock()       @标的问答（以个股事实包 + 关联资讯为上下文）
  - chat_free()        自由问答（按问题关键词检索相关资讯注入）
  - dispatch_chat()    斜杠命令（/复盘）与上下文分派
  - export_report()    报告导出（md/txt/json）
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from finfeed.llm import collector, context, store
from finfeed.llm import config as cfg
from finfeed.llm import prompts as llm_prompts
from finfeed.llm.client import LLMError, build_chat_url, build_client, build_models_url
from finfeed.llm.schema import ensure_tables
from finfeed.llm.service import get_service
from finfeed.utils.time_utils import bj_str_from_ts, now_bj

logger = logging.getLogger("news_monitor")

_HISTORY_LIMIT = 8  # 追问/问答携带的历史轮数上限
_MESSAGE_MAX_CHARS = 4000  # 单条历史消息截断长度


# 状态与首屏
def status_payload() -> Dict[str, Any]:
    providers = cfg.list_providers()
    default = cfg.get_default_provider()
    svc = get_service()
    dp = default.to_dict() if default else None
    # 模型可用性：存在默认配置 + 已启用 + (已配置密钥 或 已连通测试)
    available = False
    if default and dp:
        available = bool(default.enabled) and (
            bool(dp.get("has_api_key")) or default.test_status == 1
        )
    return {
        "provider_count": len(providers),
        "default_provider": dp,
        "available": available,
        "busy": svc.is_busy(),
        "active_task": svc.get_active(),
        "server_time": now_bj().strftime("%Y-%m-%d %H:%M:%S"),
    }


def init_payload() -> Dict[str, Any]:
    """一次返回首页所需的全部初始化数据，减少视图切换时的往返次数"""
    return {
        "presets": cfg.PRESETS,
        "scopes": [{"key": k, "label": v} for k, v in collector.SCOPES.items()],
        "windows": list(collector.ALLOWED_WINDOWS),
        "report_types": [
            {"key": k, **v} for k, v in llm_prompts.REPORT_TYPES.items()
        ],
        "status": status_payload(),
        "providers": [p.to_dict() for p in cfg.list_providers()],
        "reports": store.list_reports(limit=30, offset=0).get("items", []),
        "defaults": analysis_defaults(),
    }


def prompts_payload() -> Dict[str, Any]:
    from finfeed.llm import prompts as _prompts

    return {
        "defaults": _prompts.DEFAULT_PROMPTS,
        "custom": {k: cfg.get_setting("prompt_" + k, "") for k in _prompts.DEFAULT_PROMPTS},
    }


def save_prompts(values: Dict[str, str]) -> int:
    """保存用户自定义提示词；空值视为清除回退默认。返回写入条数。"""
    from finfeed.llm import prompts as _prompts

    saved = 0
    for k in _prompts.DEFAULT_PROMPTS:
        if k not in values:
            continue
        v = values[k]
        cfg.set_setting("prompt_" + k, "" if not str(v).strip() else str(v))
        saved += 1
    return saved


# 智能体画像（结构化角色字段 + 提示词覆盖）
def agents_payload() -> Dict[str, Dict[str, str]]:
    """返回全部智能体画像（name/personality/stance/style/tone/system_prompt）。

    附默认画像做前端「恢复默认」参照（defaults）。
    """
    from finfeed.llm import prompts as _prompts
    from finfeed.llm.schema import _AGENT_DEFAULTS

    current = cfg.list_agents()
    known_keys = list(dict.fromkeys(list(_AGENT_DEFAULTS) + list(_prompts.REPORT_TYPES.keys())))
    meta = {
        key: {"label": _prompts.REPORT_TYPES.get(key, {}).get("label", key)}
        for key in known_keys
    }
    # 让每个已知类型在列表里都有位（含 chat 自由问答）
    for key in known_keys:
        current.setdefault(key, {
            "name": "", "personality": "", "stance": "",
            "style": "", "tone": "", "system_prompt": "",
        })
    return {
        "agents": current,
        "defaults": {k: dict(v) for k, v in (_AGENT_DEFAULTS or {}).items()},
        "meta": meta,
    }


def save_agents(agents: Dict[str, Dict[str, str]]) -> int:
    """保存多个智能体画像；空字段原样写入（表示清空）。返回写入条数。"""
    if not isinstance(agents, dict):
        return 0
    cfg.save_agents(agents)
    return len(agents)


# 分析默认值（服务端持久化，跨设备共享；localStorage 仅作兜底）
def analysis_defaults() -> Dict[str, Any]:
    try:
        scope = cfg.get_setting("default_scope", "all")
        if scope not in collector.SCOPES:
            scope = "all"
        try:
            window = int(cfg.get_setting("default_window", "24"))
        except ValueError:
            window = 24
        window = collector.normalize_window(window)
        report_type = cfg.get_setting("default_report_type", "review")
        if report_type not in llm_prompts.REPORT_TYPES:
            report_type = "review"
        return {
            "scope": scope,
            "window": window,
            "focus": cfg.get_setting("default_focus", ""),
            "report_type": report_type,
        }
    except Exception as e:  # noqa: BLE001 —— 设置读取失败回退内置默认
        logger.debug(f"读取分析默认值失败: {e}")
        return {"scope": "all", "window": 24, "focus": "", "report_type": "review"}


def save_analysis_defaults(payload: Dict[str, Any]) -> Dict[str, Any]:
    """保存分析默认值；返回保存后的完整默认值。"""
    if "scope" in payload and payload["scope"] in collector.SCOPES:
        cfg.set_setting("default_scope", str(payload["scope"]))
    if "window" in payload:
        try:
            cfg.set_setting("default_window", str(collector.normalize_window(int(payload["window"]))))
        except (TypeError, ValueError):
            pass
    if "focus" in payload:
        cfg.set_setting("default_focus", str(payload.get("focus") or ""))
    if "report_type" in payload and payload["report_type"] in llm_prompts.REPORT_TYPES:
        cfg.set_setting("default_report_type", str(payload["report_type"]))
    return analysis_defaults()


# 预估
def preview_estimate(matched: int, max_items: int) -> Dict[str, Any]:
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


def provider_test_result(provider, result: Dict[str, Any]) -> Dict[str, Any]:
    """补全连通性检测响应并持久化检测结果"""
    result["provider_name"] = provider.name
    result["model"] = provider.model
    result["chat_url"] = build_chat_url(provider.base_url)
    result["models_url"] = build_models_url(provider.base_url)
    if provider.id:
        try:
            cfg.update_test_result(
                provider.id,
                result["ok"],
                result.get("message", ""),
                result.get("latency_ms", 0.0),
            )
        except Exception as e:  # noqa: BLE001 —— 检测结果落库失败不影响响应
            logger.debug(f"写入检测结果失败: {e}")
    return result


# 对话：报告追问 / 自由问答
def _provider_or_error() -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """返回 (provider, error_payload)；error 非 None 时调用方应直接中止。"""
    provider = cfg.get_default_provider()
    if provider is None:
        return None, {"ok": False, "error": "尚未配置任何大语言模型"}
    if not provider.enabled:
        return None, {"ok": False, "error": f"配置「{provider.name}」已被禁用"}
    return provider, None


def _build_history_messages(history: Any) -> List[Dict[str, str]]:
    messages: List[Dict[str, str]] = []
    if isinstance(history, list):
        for m in history[-_HISTORY_LIMIT:]:
            if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
                messages.append(
                    {
                        "role": m["role"],
                        "content": str(m["content"])[:_MESSAGE_MAX_CHARS],
                    }
                )
    return messages


def _stats_block_from_report(rep: Dict[str, Any]) -> str:
    stats = rep.get("stats") or {}
    if not stats:
        return ""
    lines = [
        f"- 样本条数：{stats.get('total', 0)} 条",
        f"- 情绪分布：正面 {stats.get('sentiment', {}).get('positive', 0)} / "
        f"中性 {stats.get('sentiment', {}).get('neutral', 0)} / "
        f"负面 {stats.get('sentiment', {}).get('negative', 0)}",
        f"- 多空比（正/多空）：{stats.get('bull_ratio', '-')}%",
    ]
    if stats.get("top_stocks"):
        lines.append(
            "- 提及最多个股："
            + "、".join(
                f"{s['name']}({s['code']}) {s['count']}次" for s in stats["top_stocks"][:12]
            )
        )
    return "\n".join(lines)


def chat_report(report_id: int, question: str, history: Any = None) -> Dict[str, Any]:
    """报告追问：以报告正文 + 程序统计为上下文回答用户问题。"""
    rep = store.get_report(report_id)
    if not rep:
        raise LLMError("报告不存在", kind="not_found")

    provider, err = _provider_or_error()
    if err or provider is None:
        return err  # type: ignore[return-value]

    context = f"""你正在协助用户深入解读一份由 FinFeed 生成的财经复盘报告。请只依据以下材料回答，不要编造数据或材料之外的信息。

【报告信息】
标题：{rep.get("title") or ""}
模型：{rep.get("model") or ""}
时间窗口：{rep.get("window_hours") or 24} 小时，覆盖 {rep.get("news_count") or 0} 条资讯

【程序统计】
{_stats_block_from_report(rep) or "（无）"}

【报告正文】
{rep.get("content") or ""}

用户可能会针对报告中的某个结论、个股、板块、数据或风险点提问。回答要求：
1. 简洁、直接、结构清晰（要点列表优先）；
2. 引用报告内容时注明出处章节；
3. 报告未提及的信息，明确说明"报告中未涉及"，不要自行发挥；
4. 涉及投资判断时给出风险提示。"""

    client = build_client(provider)
    messages: List[Dict[str, str]] = [{"role": "system", "content": context}]
    messages.extend(_build_history_messages(history))
    messages.append({"role": "user", "content": question[:_MESSAGE_MAX_CHARS]})

    res = client.chat(messages, temperature=0.3)
    return {
        "ok": True,
        "reply": res.content.strip(),
        "model": res.model or provider.model,
        "prompt_tokens": res.prompt_tokens,
        "completion_tokens": res.completion_tokens,
    }


def chat_stock(stock_code: str, stock_name: str, question: str, history: Any = None) -> Dict[str, Any]:
    """@标的问答：以个股事实包 + 关联资讯为上下文回答用户问题。"""
    provider, err = _provider_or_error()
    if err or provider is None:
        return err  # type: ignore[return-value]

    pack = context.stock_fact_pack(stock_code)
    facts_text = context.stock_fact_to_text(pack)
    news_lines = []
    for n in (pack.get("news") or [])[:12]:
        news_lines.append(f"- [{n.get('publish_time') or ''}] {n.get('source') or ''} {n.get('title')}")

    system_prompt = f"""你是 FinFeed 的个股分析助手，正在回答用户关于 {stock_name or stock_code}（{stock_code}）的问题。
当前时间：{now_bj().strftime("%Y-%m-%d %H:%M")}（北京时间）。

{facts_text or "（个股事实数据暂缺）"}

【近期关联资讯】
{chr(10).join(news_lines) if news_lines else "（暂无关联资讯）"}

回答要求：
1. 简洁、直接、结构清晰（要点列表优先）；
2. 数字只能来自上方事实包或资讯，不得编造；事实包未覆盖的维度明确说明"数据未覆盖"；
3. 涉及投资判断时给出风险提示。"""

    client = build_client(provider)
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(_build_history_messages(history))
    messages.append({"role": "user", "content": question[:_MESSAGE_MAX_CHARS]})

    res = client.chat(messages, temperature=0.3)
    return {
        "ok": True,
        "reply": res.content.strip(),
        "model": res.model or provider.model,
        "prompt_tokens": res.prompt_tokens,
        "completion_tokens": res.completion_tokens,
    }


def chat_free(question: str, history: Any = None) -> Dict[str, Any]:
    """自由问答：基于近期新闻/舆情数据做通用财经问答。"""
    provider, err = _provider_or_error()
    if err or provider is None:
        return err  # type: ignore[return-value]

    news_context = _load_recent_news_context(question=question)
    system_prompt = f"""你是 FinFeed 的财经 AI 助手，擅长回答市场、新闻、投资相关问题。
当前时间：{now_bj().strftime("%Y-%m-%d %H:%M")}（北京时间）。

{news_context}

回答要求：
1. 简洁、直接、结构清晰；
2. 涉及具体数据时给出来源和时间；
3. 不确定的信息明确说明；
4. 涉及投资判断时给出风险提示。"""

    client = build_client(provider)
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(_build_history_messages(history))
    messages.append({"role": "user", "content": question[:_MESSAGE_MAX_CHARS]})

    res = client.chat(messages, temperature=0.4)
    return {
        "ok": True,
        "reply": res.content.strip(),
        "model": res.model or provider.model,
        "prompt_tokens": res.prompt_tokens,
        "completion_tokens": res.completion_tokens,
    }


_SLASH_HANDLERS = ("/复盘",)


def dispatch_chat(
    question: str,
    report_id: int,
    history: Any = None,
    stock_code: str = "",
    stock_name: str = "",
) -> Dict[str, Any]:
    """对话入口分派：斜杠命令 > 报告追问 > @标的 > 自由问答。

    领域错误（LLMError.kind == "not_found"）转译为业务错误载荷，
    由传输层映射为 404。
    """
    question = (question or "").strip()

    # 斜杠命令：/复盘 —— 直接提交一次复盘分析任务（复用服务端保存的默认值）
    if question.startswith("/复盘"):
        args = question[len("/复盘"):].strip()
        defaults = analysis_defaults()
        options = {
            "hours": defaults["window"],
            "scope": defaults["scope"],
            "focus": args or defaults["focus"],
            "report_type": "review",
        }
        result = get_service().submit(options)
        if result.get("ok"):
            queued = "（排队中）" if result.get("queued") else ""
            return {
                "ok": True,
                "type": "task",
                "task_id": result.get("task_id"),
                "reply": f"✅ 已提交复盘简报生成任务{queued}，任务编号 {result.get('task_id')}。"
                "可在「任务中心」查看进度，完成后自动归档到研究报告。",
            }
        return {"ok": False, "error": result.get("error") or "任务提交失败", "kind": "conflict"}

    if report_id > 0:
        try:
            return chat_report(report_id, question, history)
        except LLMError as e:
            if e.kind == "not_found":
                return {"ok": False, "error": "报告不存在", "kind": "not_found"}
            raise

    if stock_code:
        return chat_stock(stock_code, stock_name, question, history)

    return chat_free(question, history)


def _load_recent_news_context(question: str = "", max_items: int = 15) -> str:
    """加载对话上下文资讯：优先按问题关键词检索（标题+正文），不足时回退最近条目。

    时间过滤统一使用 unix 秒比较，避免 localtime 语义跨机漂移。
    """
    from finfeed.storage.database import get_db

    cutoff = now_bj().timestamp() - 48 * 3600
    rows = []
    try:
        with get_db() as c:
            # 关键词命中（2 字以上的连续片段）
            tokens = [
                t for t in re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", question or "") if len(t) >= 2
            ][:6]
            if tokens:
                seen_ids: set = set()
                for tok in tokens:
                    c.execute(
                        "SELECT title, intro, source, importance, sentiment, publish_ts FROM news "
                        "WHERE publish_ts >= ? AND (title LIKE ? OR intro LIKE ?) "
                        "ORDER BY importance DESC, publish_ts DESC LIMIT 8",
                        (int(cutoff), f"%{tok}%", f"%{tok}%"),
                    )
                    for r in c.fetchall():
                        if r[0] in seen_ids:
                            continue
                        seen_ids.add(r[0])
                        rows.append(r)
                        if len(rows) >= max_items:
                            break
                    if len(rows) >= max_items:
                        break
            # 回退：最近条目（带正文摘要）
            if len(rows) < max_items:
                c.execute(
                    "SELECT title, intro, source, importance, sentiment, publish_ts FROM news "
                    "WHERE publish_ts >= ? ORDER BY publish_ts DESC LIMIT ?",
                    (int(cutoff), max_items),
                )
                for r in c.fetchall():
                    if r[0] in {x[0] for x in rows}:
                        continue
                    rows.append(r)
                    if len(rows) >= max_items:
                        break
    except Exception as e:  # noqa: BLE001 —— 上下文缺失降级为无背景问答
        logger.debug(f"加载新闻上下文失败: {e}")
        return ""

    if not rows:
        return ""

    imp_map = ((8, "⚠️极重要"), (6, "🔴重要"), (3, "🟡一般"))
    sent_map = {"positive": "😊正面", "negative": "😟负面", "neutral": "😐中性"}
    lines = ["【相关资讯摘要（最近 48 小时，含正文摘要）】"]
    for r in rows:
        importance = float(r[3] or 0)
        imp = next((label for floor, label in imp_map if importance >= floor), "⚪较低")
        sent = sent_map.get(r[4], "")
        ts_str = bj_str_from_ts(int(r[5]))[5:16] if r[5] else ""
        src = r[2] or ""
        intro = " ".join(str(r[1] or "").split())[:120]
        title = " ".join(str(r[0] or "").split())
        body = f"｜{intro}" if intro and intro[:20] not in title else ""
        lines.append(f"- [{ts_str}] {src} {imp}{sent} {title}{body}")
    return "\n".join(lines) + "\n"


# 导出
def export_report(report_id: int, fmt: str = "md") -> Optional[Tuple[str, bytes, str]]:
    """返回 (文件名, 内容字节, Content-Type)"""
    ensure_tables()
    rep = store.get_report(report_id)
    if not rep:
        return None
    ts = rep.get("created_at") or now_bj().strftime("%Y-%m-%d %H:%M:%S")
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
    return (
        f"finfeed_ai_report_{stamp}.json",
        json.dumps(rep, ensure_ascii=False, indent=2).encode("utf-8"),
        "application/json; charset=utf-8",
    )
