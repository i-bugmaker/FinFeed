#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极薄分析器注册表 + 运行器 + 各报告类型专用分析器。

架构：
  - Analyzer 抽象基类：每个报告类型对应一个可选专用分析器（新需求 = 新增一个子类并注册）。
  - run_analysis 顶层只做分发：get_analyzer(report_type) 命中则调用专用分析器，
    否则回退 analyzer._run_legacy（review/stock/sentiment 保持原逻辑不动）。
  - FlashAnalyzer：单条快讯「单次直成文」，绝无 chunk/MAP 分批压缩。

通过 analyzer.py 底部 `from . import analyzers as _` 触发本模块注册。
"""

import json
import logging
import time
from typing import Any, Callable, Dict, Optional

from . import collector, context, prompts
from .client import LLMClient, LLMError, estimate_tokens
from .config import agent_system, get_prompts

from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

ProgressFn = Callable[[str, float, str], None]
CancelFn = Callable[[], bool]


class Runner:
    """生成运行器：进度上报 / 取消检查 / 流式增量 / token 记账（供专用分析器复用）。"""

    def __init__(self, client, *, progress=None, should_cancel=None, on_delta=None):
        self.client = client
        self._progress = progress
        self._should_cancel = should_cancel
        self._on_delta = on_delta
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def progress(self, stage: str, pct: float, msg: str) -> None:
        if self._progress:
            try:
                self._progress(stage, pct, msg)
            except Exception:  # noqa: BLE001 —— 进度回调异常不影响分析主流程
                pass

    def check(self) -> None:
        if self._should_cancel and self._should_cancel():
            from .analyzer import AnalysisCancelled  # 延迟导入，避免循环
            raise AnalysisCancelled()

    def _safe_delta(self, piece: str) -> None:
        if self._on_delta:
            try:
                self._on_delta(piece)
            except Exception:  # noqa: BLE001
                pass

    def _consume_stream(self, stream, est_messages) -> str:
        buf = []
        usage_seen = False
        for ev in stream:
            if ev.get("type") == "usage":
                self.prompt_tokens += int(ev.get("prompt_tokens") or 0)
                self.completion_tokens += int(ev.get("completion_tokens") or 0)
                usage_seen = True
            elif ev.get("type") == "delta":
                piece = ev.get("text") or ""
                if piece:
                    buf.append(piece)
                    self._safe_delta(piece)
        content = "".join(buf).strip()
        if not usage_seen:
            # 服务端未回传 usage：按字数近似（页脚已标注「token 约」）
            self.prompt_tokens += estimate_tokens(json.dumps(est_messages, ensure_ascii=False))
            self.completion_tokens += estimate_tokens(content)
        return content

    def generate(self, system_prompt: str, user_prompt: str, cap: Optional[int] = None) -> str:
        """生成正文：流式优先，任何失败回退一次性调用保证结果完整性。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        max_tok = min(self.client.max_tokens, cap) if cap else None
        try:
            stream = self.client.chat_stream(messages, max_tokens=max_tok)
            content = self._consume_stream(stream, messages)
            if content:
                return content
            logger.warning("LLM 流式返回空内容，回退非流式重取")
        except LLMError as e:
            logger.warning(f"LLM 流式失败，回退非流式: {e.message}")

        # 回退：通知前端清空半成品缓冲，再整段补发权威正文
        self._safe_delta("")
        res = self.client.chat(messages, max_tokens=max_tok)
        self.prompt_tokens += res.prompt_tokens
        self.completion_tokens += res.completion_tokens
        text = res.content.strip()
        if not text:
            raise LLMError("模型返回内容为空", kind="empty")
        self._safe_delta(text)
        return text


class Analyzer:
    """分析器抽象基类。子类声明 report_type 并实现 run()。"""

    report_type: str = ""

    def run(self, client: LLMClient, *, hours: int = 24,
            scope: str = collector.SCOPE_ALL, report_type: str = "",
            stock_code: str = "", min_importance: float = 0.0, max_items: int = 500,
            order: str = collector.ORDER_IMPORTANCE, chunk_chars: int = 8000,
            max_chunks: int = 20, focus: str = "", news_id: Optional[int] = None,
            progress: Optional[ProgressFn] = None,
            should_cancel: Optional[CancelFn] = None,
            on_delta: Optional[Callable[[str], None]] = None, **kw) -> Dict[str, Any]:
        raise NotImplementedError


class FlashAnalyzer(Analyzer):
    """快讯分析（report_type='flash'）：围绕单条快讯单次直成文，绝不分批。"""

    report_type = "flash"

    def run(self, client: LLMClient, *, hours: int = 24, focus: str = "",
            news_id: Optional[int] = None, progress=None, should_cancel=None,
            on_delta=None, **kw) -> Dict[str, Any]:
        runner = Runner(client, progress=progress, should_cancel=should_cancel,
                        on_delta=on_delta)
        # 生效提示词（内置默认 + 用户 prompt 覆盖）
        from . import analyzer as _mod  # 延迟导入 _safe_format，避免顶部循环
        P = get_prompts()
        t_start = time.time()
        runner.progress("collect", 3, "正在回查目标快讯并采集相关佐证…")

        records, meta = collector.collect_flash(
            news_id=news_id, focus=focus, hours=hours, max_related=15
        )
        if not records:
            raise LLMError(
                f"未找到该快讯（近 {hours} 小时库内无相关记录），请确认快讯仍存在或放宽时间窗口",
                kind="empty_data",
            )
        runner.check()
        runner.progress("stats", 10, f"读取目标快讯 1 条 + 相关佐证 {max(0, len(records) - 1)} 条")

        # 市场事实包（可选，失败静默降级）
        facts_text = "（本快讯分析未附带市场事实包）"
        try:
            facts_block = context.market_fact_to_text(context.market_fact_pack())
            if facts_block:
                facts_text = facts_block
        except Exception as e:  # noqa: BLE001 —— 事实层失败不影响快讯分析
            logger.debug(f"快讯分析事实包降级: {e}")

        target = records[0]
        win_label = prompts.window_label(meta["hours"])
        sources = _mod._build_sources(records)
        payload_lines = "\n".join(r.to_line(i) for i, r in enumerate(records, 1))
        user = _mod._safe_format(
            P["flash_user"], prompts.FLASH_USER_TEMPLATE,
            window_label=win_label,
            news_count=len(records),
            focus=(focus or target.title),
            payload=payload_lines,
            facts_block=facts_text,
        )
        runner.progress("reduce", 30, "正在围绕目标快讯进行单次分析…")
        body = runner.generate(agent_system("flash", P["flash_system"]), user, cap=None)
        runner.progress("assemble", 96, "正在拼装报告…")

        elapsed = time.time() - t_start
        generated_at = now_bj().strftime("%Y-%m-%d %H:%M:%S")
        focus_title = (focus or target.title).strip().split("|")[0].split("｜")[0].strip()
        if len(focus_title) > 26:
            focus_title = focus_title[:26] + "…"
        title = f"快讯分析 · {focus_title} · {generated_at[:16]}"

        header = "\n".join([
            f"# {title}", "",
            f"> 生成时间：{generated_at}　|　分析模型：{client.model}　|　"
            f"覆盖区间：{meta['start_str']} — {meta['end_str']}", "",
            "---", "",
        ])
        footer = "\n".join([
            "", "---", "",
            f"*本报告由 FinFeed AI 分析模块生成。样本 {len(records)} 条 / 单批直成文 / "
            f"耗时 {elapsed:.1f} 秒 / token 约 {runner.prompt_tokens + runner.completion_tokens}。"
            "结论由大语言模型基于目标快讯与库内佐证资讯归纳，不构成投资建议。*",
        ])
        content = header + body.strip() + "\n" + footer

        return {
            "title": title,
            "content": content,
            "stats": {},
            "meta": meta,
            "report_type": "flash",
            "stock_code": "",
            "sources": sources,
            "news_count": len(records),
            "scanned_count": meta["scanned_count"],
            "chunk_count": 1,
            "prompt_tokens": runner.prompt_tokens,
            "completion_tokens": runner.completion_tokens,
            "elapsed": round(elapsed, 2),
            "window_hours": meta["hours"],
            "scope": meta.get("scope", collector.SCOPE_ALL),
            "start_ts": meta["start_ts"],
            "end_ts": meta["end_ts"],
            "model": client.model,
        }


# 注册表
_ANALYZERS: Dict[str, Analyzer] = {}


def register_analyzer(a: Analyzer) -> Analyzer:
    if a.report_type:
        _ANALYZERS[a.report_type] = a
    return a


def get_analyzer(report_type: str) -> Optional[Analyzer]:
    return _ANALYZERS.get(report_type)


register_analyzer(FlashAnalyzer())