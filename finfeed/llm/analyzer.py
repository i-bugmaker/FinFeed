#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归纳分析引擎（map-reduce）

流程：
  1. 采集窗口内新闻
  2. 程序侧确定性统计（来源/情绪/热门个股/高分要闻/时段分布）—— 数字不交给模型算
  3. 分块 MAP：每块压缩成结构化要点
  4. REDUCE：汇总要点，产出结构化复盘简报
  5. 拼装最终 Markdown（统计概览 + 模型报告 + 元信息）

小数据量（单块可容纳）时自动走单次调用，省一轮开销。
"""

import json
import logging
import time
from collections import Counter, defaultdict
from typing import Any, Callable, Dict, List, Optional

from finfeed.storage.database import get_db_manager
from finfeed.utils.time_utils import bj_str_from_ts, now_bj

from . import collector, context, prompts
from .cleanup import clean_report_body
from .client import LLMClient, LLMError, estimate_tokens
from .collector import NewsRecord
from .config import get_prompts
from .decorate import decorate_report_body

logger = logging.getLogger("news_monitor")

ProgressFn = Callable[[str, float, str], None]
CancelFn = Callable[[], bool]


class AnalysisCancelled(Exception):
    """用户主动取消"""


# 确定性统计
def _stock_names(codes: List[str]) -> Dict[str, str]:
    if not codes:
        return {}
    out: Dict[str, str] = {}
    try:
        db = get_db_manager()
        with db.get_db() as c:
            for i in range(0, len(codes), 400):
                batch = codes[i : i + 400]
                ph = ",".join("?" * len(batch))
                c.execute(f"SELECT code, name FROM stock_meta WHERE code IN ({ph})", batch)
                for r in c.fetchall():
                    out[r["code"]] = r["name"]
    except Exception as e:
        logger.debug(f"股票名映射查询失败: {e}")
    return out


def compute_stats(records: List[NewsRecord], meta: Dict[str, Any]) -> Dict[str, Any]:
    """程序侧统计，保证报告中的数字准确"""
    total = len(records)
    sources = Counter(r.source for r in records if r.source)
    sentiment = Counter(r.sentiment or "neutral" for r in records)
    categories = Counter(r.category or "未分类" for r in records)

    stock_counter: Counter = Counter()
    for r in records:
        for code in r.stocks:
            stock_counter[code] += 1
    top_codes = [c for c, _ in stock_counter.most_common(20)]
    name_map = _stock_names(top_codes)
    top_stocks = [
        {"code": code, "name": name_map.get(code, code), "count": cnt}
        for code, cnt in stock_counter.most_common(20)
    ]

    kw_counter: Counter = Counter()
    for r in records:
        for k in r.keywords[:6]:
            if len(k) >= 2:
                kw_counter[k] += 1
    top_keywords = [{"word": w, "count": n} for w, n in kw_counter.most_common(20)]

    hourly: Dict[str, int] = defaultdict(int)
    for r in records:
        if r.publish_ts:
            hourly[bj_str_from_ts(r.publish_ts)[:13]] += 1

    top_news = sorted(records, key=lambda x: (-x.importance, -x.publish_ts))[:15]
    top_news_list = [
        {
            "title": n.title[:80],
            "source": n.source,
            "time": (n.publish_time or bj_str_from_ts(n.publish_ts))[:16],
            "importance": round(n.importance, 1),
            "sentiment": n.sentiment,
            "url": n.url,
        }
        for n in top_news
    ]

    imp_buckets = {
        "极重要(≥8)": sum(1 for r in records if r.importance >= 8),
        "重要(6-8)": sum(1 for r in records if 6 <= r.importance < 8),
        "一般(<6)": sum(1 for r in records if r.importance < 6),
    }

    pos = sentiment.get("positive", 0)
    neg = sentiment.get("negative", 0)
    neu = sentiment.get("neutral", 0)
    denom = pos + neg
    bull_ratio = round(pos / denom * 100, 1) if denom else 50.0

    return {
        "total": total,
        "scanned": meta.get("scanned_count", total),
        "truncated": meta.get("truncated", False),
        "window_hours": meta.get("hours", 24),
        "scope_label": meta.get("scope_label", ""),
        "start_str": meta.get("start_str", ""),
        "end_str": meta.get("end_str", ""),
        "sources": [{"name": n, "count": c} for n, c in sources.most_common(15)],
        "source_total": len(sources),
        "sentiment": {"positive": pos, "neutral": neu, "negative": neg},
        "bull_ratio": bull_ratio,
        "categories": [{"name": n, "count": c} for n, c in categories.most_common(10)],
        "top_stocks": top_stocks,
        "top_keywords": top_keywords,
        "importance_buckets": imp_buckets,
        "hourly": dict(sorted(hourly.items())),
        "top_news": top_news_list,
    }


def stats_to_prompt_block(stats: Dict[str, Any]) -> str:
    """压缩成提示词里的统计片段"""
    lines = [
        f"- 样本条数：{stats['total']} 条（窗口内命中 {stats['scanned']} 条"
        + ("，已按重要性截断" if stats.get("truncated") else "")
        + "）",
        f"- 覆盖信源：{stats['source_total']} 家，"
        + "、".join(f"{s['name']}{s['count']}条" for s in stats["sources"][:8]),
        f"- 情绪分布：正面 {stats['sentiment']['positive']} / 中性 {stats['sentiment']['neutral']} "
        f"/ 负面 {stats['sentiment']['negative']}（正面占多空比 {stats['bull_ratio']}%）",
        "- 重要性分布：" + "、".join(f"{k} {v}条" for k, v in stats["importance_buckets"].items()),
    ]
    if stats["top_stocks"]:
        lines.append(
            "- 提及最多个股："
            + "、".join(
                f"{s['name']}({s['code']}) {s['count']}次" for s in stats["top_stocks"][:12]
            )
        )
    if stats["top_keywords"]:
        lines.append("- 高频关键词：" + "、".join(k["word"] for k in stats["top_keywords"][:15]))
    return "\n".join(lines)


def stats_to_markdown(stats: Dict[str, Any]) -> str:
    """报告开头的确定性数据概览"""
    s = stats
    md = [
        "## 数据概览",
        "",
        f"- **时间窗口**：{s['start_str']} — {s['end_str']}（近 {s['window_hours']} 小时）",
        f"- **数据范围**：{s['scope_label']}",
        f"- **窗口命中**：{s['scanned']} 条；**送入分析**：{s['total']} 条"
        + ("（按重要性优先截断）" if s.get("truncated") else ""),
        f"- **覆盖信源**：{s['source_total']} 家",
        f"- **情绪分布**：正面 {s['sentiment']['positive']} 条 / 中性 {s['sentiment']['neutral']} 条 "
        f"/ 负面 {s['sentiment']['negative']} 条（正面占多空比 **{s['bull_ratio']}%**）",
        "",
    ]

    if s["sources"]:
        md += ["**信源分布 Top 10**", "", "| 信源 | 条数 |", "| --- | ---: |"]
        md += [f"| {x['name']} | {x['count']} |" for x in s["sources"][:10]]
        md.append("")

    if s["top_stocks"]:
        md += ["**提及最多个股 Top 10**", "", "| 个股 | 代码 | 提及次数 |", "| --- | --- | ---: |"]
        md += [f"| {x['name']} | {x['code']} | {x['count']} |" for x in s["top_stocks"][:10]]
        md.append("")

    if s["top_news"]:
        md += ["**重要性最高的 10 条原始资讯**", ""]
        for i, n in enumerate(s["top_news"][:10], 1):
            title = n["title"].replace("|", "／")
            if n.get("url") and n["url"] != "#":
                md.append(
                    f"{i}. [{title}]({n['url']}) — {n['source']}｜{n['time']}｜重要性 {n['importance']}"
                )
            else:
                md.append(f"{i}. {title} — {n['source']}｜{n['time']}｜重要性 {n['importance']}")
        md.append("")

    return "\n".join(md)


# 主流程
def _safe_format(template: str, default: str, **kw) -> str:
    """用模板格式化；若用户自定义模板缺少占位符导致 KeyError，回退内置默认。"""
    try:
        return template.format(**kw)
    except (KeyError, IndexError, ValueError) as e:
        logger.warning(f"提示词模板占位符缺失，回退内置默认: {e}")
        return default.format(**kw)


def _build_sources(records: List[NewsRecord]) -> List[Dict[str, Any]]:
    """构建引用溯源映射：资讯清单编号 [idx] -> 原始新闻（供阅读器回链）。"""
    return [
        {
            "idx": i,
            "id": r.id,
            "title": r.title,
            "source": r.source,
            "time": r.publish_time or bj_str_from_ts(r.publish_ts),
            "url": r.url,
            "importance": round(r.importance, 1),
        }
        for i, r in enumerate(records, 1)
    ]


def run_analysis(
    client: LLMClient,
    *,
    hours: int = 24,
    scope: str = collector.SCOPE_ALL,
    report_type: str = "review",
    stock_code: str = "",
    min_importance: float = 0.0,
    max_items: int = 500,
    order: str = collector.ORDER_IMPORTANCE,
    chunk_chars: int = 8000,
    max_chunks: int = 20,
    focus: str = "",
    progress: Optional[ProgressFn] = None,
    should_cancel: Optional[CancelFn] = None,
    on_delta: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """执行一次完整分析，返回报告 payload

    report_type: review 复盘简报（map-reduce/单轮）｜stock 个股深度｜sentiment 舆情研判
    on_delta: 生成正文阶段的增量回调，用于 SSE 渐进输出。
      - 每收到一段模型增量调用一次 on_delta(piece)；
      - 流式中断回退非流式重取时，先以 on_delta("") 作为「清空缓冲」信号，
        再整段补发完整正文——前端据此避免拼接重复内容。
    """
    if report_type not in prompts.REPORT_TYPES:
        report_type = "review"

    # 生效提示词（内置默认 + 用户自定义覆盖）；占位符缺失时回退内置默认
    P = get_prompts()
    t_start = time.time()

    def _p(stage: str, pct: float, msg: str):
        if progress:
            try:
                progress(stage, pct, msg)
            except Exception:
                pass

    def _check():
        if should_cancel and should_cancel():
            raise AnalysisCancelled()

    # ---------- 事实包（先于采集，失败静默降级） ----------
    _p("collect", 3, "正在汇编市场事实与资讯数据…")
    market_text = ""
    stock_name = ""
    if report_type == "stock":
        stock_code = (stock_code or "").strip()
        if not stock_code:
            raise LLMError("个股深度报告需要提供股票代码", kind="empty_data")
        facts_pack = context.stock_fact_pack(stock_code)
        if not facts_pack.get("found"):
            logger.warning(f"事实层缺少 {stock_code} 档案，仅用资讯生成")
        stock_name = (facts_pack.get("meta") or {}).get("name") or stock_code
        facts_text = context.stock_fact_to_text(facts_pack)
    elif report_type == "sentiment":
        facts_pack = context.sentiment_fact_pack()
        market_pack = context.market_fact_pack()
        facts_text = context.sentiment_fact_to_text(facts_pack)
        market_text = context.market_fact_to_text(market_pack)
    else:
        facts_pack = context.market_fact_pack()
        facts_text = context.market_fact_to_text(facts_pack)

    # ---------- 采集 ----------
    if report_type == "stock":
        records, meta = collector.collect_for_stock(stock_code, hours=hours, max_items=max_items)
    else:
        records, meta = collector.collect(
            hours=hours,
            scope=scope,
            min_importance=min_importance,
            max_items=max_items,
            order=order,
        )
    if not records:
        if report_type == "stock":
            raise LLMError(
                f"近 {hours} 小时内没有找到与 {stock_name}({stock_code}) 关联的资讯，请放宽时间窗口",
                kind="empty_data",
            )
        raise LLMError(
            f"窗口内没有符合条件的新闻（近 {hours} 小时 / {collector.SCOPES.get(scope, scope)}"
            f" / 重要性≥{min_importance}），请放宽筛选条件",
            kind="empty_data",
        )
    _check()

    _p("stats", 10, f"命中 {meta['scanned_count']} 条，选取 {len(records)} 条，正在计算统计指标…")
    stats = compute_stats(records, meta)
    stats_block = stats_to_prompt_block(stats)
    win_label = prompts.window_label(meta["hours"])
    sources = _build_sources(records)

    chunks = collector.build_chunks(records, chunk_chars=chunk_chars, max_chunks=max_chunks)
    total_chunks = len(chunks)
    _p("chunk", 14, f"已切分为 {total_chunks} 个批次，准备调用模型")

    focus_note = (
        f"\n\n【本次特别关注】{focus.strip()}\n请在报告中显著体现该关注点。"
        if focus.strip()
        else ""
    )

    prompt_tokens = 0
    completion_tokens = 0

    def _safe_delta(piece: str) -> None:
        if not on_delta:
            return
        try:
            on_delta(piece)
        except Exception:  # noqa: BLE001 —— 前端回调异常不影响分析主流程
            pass

    def _consume_stream(stream, est_messages: List[Dict[str, str]]) -> str:
        """消费流式事件，累计正文与 token；返回完整正文。"""
        nonlocal prompt_tokens, completion_tokens
        buf: List[str] = []
        usage_seen = False
        for ev in stream:
            if ev.get("type") == "usage":
                prompt_tokens += int(ev.get("prompt_tokens") or 0)
                completion_tokens += int(ev.get("completion_tokens") or 0)
                usage_seen = True
            elif ev.get("type") == "delta":
                piece = ev.get("text") or ""
                if piece:
                    buf.append(piece)
                    _safe_delta(piece)
        content = "".join(buf).strip()
        if not usage_seen:
            # 服务端未回传 usage：按字数近似（页脚已标注「token 约」）
            prompt_tokens += estimate_tokens(json.dumps(est_messages, ensure_ascii=False))
            completion_tokens += estimate_tokens(content)
        return content

    def _generate_final(system_prompt: str, user_prompt: str, cap: Optional[int]) -> str:
        """生成最终报告正文：流式优先，任何失败回退一次性调用保证结果完整性。"""
        nonlocal prompt_tokens, completion_tokens
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        max_tok = min(client.max_tokens, cap) if cap else None

        try:
            stream = client.chat_stream(messages, max_tokens=max_tok)
            content = _consume_stream(stream, messages)
            if content:
                return content
            logger.warning("LLM 流式返回空内容，回退非流式重取")
        except LLMError as e:
            logger.warning(f"LLM 流式失败，回退非流式: {e.message}")

        # 回退：通知前端清空半成品缓冲，再整段补发权威正文
        _safe_delta("")
        res = client.chat(messages, max_tokens=max_tok)
        prompt_tokens += res.prompt_tokens
        completion_tokens += res.completion_tokens
        text = res.content.strip()
        if not text:
            raise LLMError("模型返回内容为空", kind="empty")
        _safe_delta(text)
        return text

    def _map_digests() -> str:
        """多批时逐批压缩为要点，返回拼接后的要点文本（含失败占位）。"""
        nonlocal prompt_tokens, completion_tokens
        digests: List[str] = []
        for i, chunk in enumerate(chunks, 1):
            _check()
            pct = 14 + (i - 1) / total_chunks * 62
            _p("map", pct, f"正在压缩第 {i}/{total_chunks} 批（{len(chunk)} 条）…")
            user = _safe_format(
                P["map_user"],
                prompts.MAP_USER_TEMPLATE,
                window_label=win_label,
                index=i,
                total=total_chunks,
                count=len(chunk),
                payload="\n".join(chunk),
            )
            try:
                res = client.chat(
                    [
                        {"role": "system", "content": P["map_system"]},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=min(client.max_tokens, 2048),
                )
                prompt_tokens += res.prompt_tokens
                completion_tokens += res.completion_tokens
                digests.append(f"—— 第 {i}/{total_chunks} 批要点 ——\n{res.content.strip()}")
            except LLMError as e:
                logger.warning(f"LLM 第 {i} 批压缩失败：{e.message}")
                digests.append(f"—— 第 {i}/{total_chunks} 批要点 ——\n（该批处理失败：{e.message}）")
        ok_batches = sum(1 for d in digests if "（该批处理失败" not in d)
        if ok_batches == 0:
            raise LLMError("所有批次均调用失败，请检查模型配置与网络", kind="all_failed")
        _p("reduce", 80, f"{ok_batches}/{total_chunks} 批要点提取完成，正在汇总生成报告…")
        digest_text = "\n\n".join(digests)
        if len(digest_text) > chunk_chars * 3:
            digest_text = digest_text[: chunk_chars * 3] + "\n（要点过长，已截断）"
        return digest_text

    # ---------- 分类型生成 ----------
    if report_type == "stock":
        # 个股深度：单批直接用资讯清单；多批先 MAP 压缩再以要点为素材
        _p("reduce", 30, f"正在生成 {stock_name}({stock_code}) 深度诊断…")
        material = "\n".join(chunks[0]) if total_chunks == 1 else _map_digests()
        material_label = "关联资讯清单" if total_chunks == 1 else "经分批压缩后的关联资讯要点"
        user = (
            _safe_format(
                P["stock_user"],
                prompts.STOCK_USER_TEMPLATE,
                stock_name=stock_name,
                stock_code=stock_code,
                facts_block=facts_text or "（事实层数据暂缺，以下仅基于资讯分析）",
                stats_block=stats_block,
                window_hours=meta["hours"],
                news_count=len(records),
                payload=material,
            ).replace("【关联资讯清单】", f"【{material_label}】")
            + focus_note
        )
        body = _generate_final(P["stock_system"], user, cap=None)
    elif report_type == "sentiment":
        _p("reduce", 30, "正在生成舆情研判报告…")
        material = "\n".join(chunks[0]) if total_chunks == 1 else _map_digests()
        user = (
            _safe_format(
                P["sentiment_user"],
                prompts.SENTIMENT_USER_TEMPLATE,
                facts_block=facts_text or "（舆情事实数据暂缺）",
                facts_market_block=market_text or "（市场事实数据暂缺）",
                stats_block=stats_block,
                window_label=win_label,
                news_count=len(records),
                payload=material,
            )
            + focus_note
        )
        body = _generate_final(P["sentiment_system"], user, cap=None)
    elif total_chunks == 1:
        # ---------- 复盘简报：单批直接成文 ----------
        _check()
        _p("reduce", 30, "数据量适中，单次调用生成报告…")
        user = (
            _safe_format(
                P["single_user"],
                prompts.SINGLE_PASS_USER_TEMPLATE,
                window_label=win_label,
                start_str=meta["start_str"],
                end_str=meta["end_str"],
                news_count=len(records),
                facts_block=facts_text or "（市场事实数据暂缺）",
                stats_block=stats_block,
                payload="\n".join(chunks[0]),
            )
            + focus_note
        )
        body = _generate_final(P["reduce_system"], user, cap=None)
        _p("reduce", 92, "报告生成完成")
    else:
        # ---------- 复盘简报：MAP + REDUCE ----------
        digest_text = _map_digests()
        _check()
        user = (
            _safe_format(
                P["reduce_user"],
                prompts.REDUCE_USER_TEMPLATE,
                window_label=win_label,
                start_str=meta["start_str"],
                end_str=meta["end_str"],
                news_count=len(records),
                facts_block=facts_text or "（市场事实数据暂缺）",
                stats_block=stats_block,
                digests=digest_text,
            )
            + focus_note
        )
        body = _generate_final(P["reduce_system"], user, cap=None)
        _p("reduce", 92, "报告生成完成")

    # ---------- 拼装 ----------
    _p("assemble", 96, "正在拼装报告…")
    elapsed = time.time() - t_start
    generated_at = now_bj().strftime("%Y-%m-%d %H:%M:%S")
    if report_type == "stock":
        title = f"FinFeed 个股诊断 · {stock_name}({stock_code}) · {generated_at[:16]}"
    elif report_type == "sentiment":
        title = f"FinFeed 市场舆情研判 · {generated_at[:16]}"
    else:
        title = f"FinFeed 近{meta['hours']}小时资讯复盘 · {generated_at[:16]}"

    header = "\n".join(
        [
            f"# {title}",
            "",
            f"> 生成时间：{generated_at}　|　分析模型：{client.model}　|　"
            f"覆盖区间：{meta['start_str']} — {meta['end_str']}"
            + (f"　|　标的：{stock_name}({stock_code})" if report_type == "stock" else ""),
            "",
            "---",
            "",
        ]
    )
    footer = "\n".join(
        [
            "",
            "---",
            "",
            f"*本报告由 FinFeed AI 分析模块生成。样本 {len(records)} 条 / 分 {total_chunks} 批处理 / "
            f"耗时 {elapsed:.1f} 秒 / token 约 {prompt_tokens + completion_tokens}。"
            "结论由大语言模型基于库内公开资讯与事实数据归纳，不构成投资建议。*",
        ]
    )

    body = decorate_report_body(clean_report_body(body))
    content = header + stats_to_markdown(stats) + "\n---\n\n" + body.strip() + "\n" + footer

    return {
        "title": title,
        "content": content,
        "stats": stats,
        "meta": meta,
        "report_type": report_type,
        "stock_code": stock_code,
        "sources": sources,
        "news_count": len(records),
        "scanned_count": meta["scanned_count"],
        "chunk_count": total_chunks,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "elapsed": round(elapsed, 2),
        "window_hours": meta["hours"],
        "scope": meta.get("scope", scope),
        "start_ts": meta["start_ts"],
        "end_ts": meta["end_ts"],
        "model": client.model,
    }
