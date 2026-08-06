#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘后 tdx 情绪快照编排（方案E 执行器）

架构约束（关键）：
  - tdx_ai_listening 是 MCP 工具，Python 监控进程调不到，必须由 agent 在盘后快照层调用。
  - 其返回值是**自由文本**（markdown），"整体权重: 40" 嵌在正文里，需 agent 解析后回写。
  - 因此本模块是"agent 与数据库之间的桥梁"：agent 负责调 MCP + 抽权重，
    本模块负责算目标池、落库、聚合。

标准 agent 流程（盘后 15:30 触发）：
  pool = select_prioritized_pool(top_n=150)        # ① Python 算池
  weights = {}
  for item in pool:                                # ② agent 调 MCP
      txt = tdx_ai_listening(setcode_code=to_tdx_setcode(item["code"]), date=TD)
      weights[item["code"]] = parse_overall_weight(txt)   # ③ agent 抽权重
  apply_tdx_stock_weights(weights, TD)             # ④ Python 落库
  run_aggregation(TD)                             # ⑤ 聚合板块 + 全市场温度

也可直接听板块（tdx 支持板块代码 1_88xxxx）：
  apply_tdx_sector_weight("881084", "人工智能", "concept", w, TD)
"""

import asyncio
import json
import logging
import re
import sys
from typing import Dict, List, Optional

import httpx

from finfeed.analysis.snapshot import (
    SOURCE_NAME,
    build_sector_snapshot,
    get_stock_name,
    tdx_weight_to_record,
    write_stock_sentiment_snapshot,
)
from finfeed.storage import sentiment_store as ss
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("news_monitor")

# 东财人气榜（盘中注意力信号，用于盘后优先池）
_GUBA_RANK_API = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"


# ---------------------------------------------------------------------------
# 工具：股票代码 → tdx setcode_code
# ---------------------------------------------------------------------------
def to_tdx_setcode(code: str) -> str:
    """A股代码 → tdx_ai_listening 所需的 '市场_代码' 格式。

    沪市(60/68/90 开头) → 1；深市(00/30 开头) → 0；北交所(8/4 开头) → 2。
    """
    c = code.strip()
    if "_" in c:
        return c  # 已是 setcode 形式
    if c[:2] in ("60", "68", "90") or c.startswith("689"):
        return f"1_{c}"
    if c[:2] in ("00", "30") or c.startswith("003"):
        return f"0_{c}"
    if c[0] in ("8", "4") or c[:2] in ("43", "92"):
        return f"2_{c}"
    # 兜底：按常见规则猜
    return f"1_{c}" if c.startswith("6") else f"0_{c}"


# ---------------------------------------------------------------------------
# 工具：从 tdx 自由文本抽取整体权重
# ---------------------------------------------------------------------------
_WEIGHT_RE = re.compile(r"整体权重[:：]\s*(\d{1,3})")
_EVENT_WEIGHT_RE = re.compile(r"权重[:：]\s*(\d{1,3})\s*/\s*100")


def parse_overall_weight(text: str) -> Optional[int]:
    """从 tdx_ai_listening 返回文本抽取整体权重(0-100)。

    优先匹配"整体权重: 40"；若不存在，则退回对所有事件权重取均值。
    返回 None 表示未解析到（多为"暂无资讯数据"）。
    """
    if not text:
        return None
    m = _WEIGHT_RE.search(text)
    if m:
        return int(m.group(1))
    # 退回：平均所有事件权重
    evs = [int(x) for x in _EVENT_WEIGHT_RE.findall(text)]
    if evs:
        return round(sum(evs) / len(evs))
    return None


# ---------------------------------------------------------------------------
# ① 计算盘后快照目标池（人气榜 TopN + 涨停/跌停 + 指定板块/个股）
# ---------------------------------------------------------------------------
async def _fetch_guba_rank(top_n: int) -> List[Dict[str, str]]:
    """盘后人气榜（东财接口，runtime 有网）。返回 [{code, name, reason}]"""
    out: List[Dict[str, str]] = []
    page = 1
    seen = 0
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            while seen < top_n:
                resp = await client.get(
                    _GUBA_RANK_API,
                    params={"pageNo": page, "pageSize": min(100, top_n - seen + 10)},
                )
                data = resp.json().get("data") or {}
                lst = data.get("data") or []
                if not lst:
                    break
                for it in lst:
                    sc = (it.get("sc") or "").strip()
                    if len(sc) < 3:
                        continue
                    code = sc[2:]  # "1A600519" -> "600519"
                    out.append({"code": code, "name": get_stock_name(code),
                                "reason": f"人气榜#{it.get('rk', '?')}"})
                    seen += 1
                    if seen >= top_n:
                        break
                if len(lst) < 100:
                    break
                page += 1
    except Exception as e:  # 网络异常时不阻塞，返回已获取的
        logger.warning(f"人气榜拉取失败（沿用已有）: {e}")
    return out


def select_prioritized_pool(top_n: int = 150,
                            extra_codes: Optional[List[str]] = None,
                            boards: Optional[List[Dict[str, str]]] = None,
                            include_rank: bool = True) -> List[Dict[str, str]]:
    """计算盘后 tdx 快照目标池。

    Args:
        top_n:       人气榜取前 N 只（注意力信号最强）
        extra_codes: 额外指定个股（如涨停/跌停、自选）
        boards:      额外指定板块监听 [{board_code, board_name, sector_type}]
        include_rank: 是否纳入人气榜
    Returns:
        [{code, name, reason}]  —— 去重后的个股池（板块另走 apply_tdx_sector_weight）
    """
    pool: List[Dict[str, str]] = []
    if include_rank:
        pool.extend(asyncio.run(_fetch_guba_rank(top_n)))
    if extra_codes:
        for code in extra_codes:
            pool.append({"code": code, "name": get_stock_name(code), "reason": "指定标的"})
    # 去重（保留首次出现）
    seen = set()
    dedup = []
    for it in pool:
        if it["code"] in seen:
            continue
        seen.add(it["code"])
        dedup.append(it)
    return dedup


# ---------------------------------------------------------------------------
# ④ 落库：个股权重
# ---------------------------------------------------------------------------
def apply_tdx_stock_weights(weight_map: Dict[str, Optional[int]],
                            trade_date: Optional[str] = None,
                            source: str = SOURCE_NAME) -> int:
    """agent 收集的 {code: 整体权重(0-100)} → stock_sentiment（幂等 upsert）。

    权重为 None 的条目跳过（无资讯数据，不污染聚合）。
    """
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    recs = []
    skipped = 0
    for code, w in weight_map.items():
        if w is None:
            skipped += 1
            continue
        recs.append(tdx_weight_to_record(code, get_stock_name(code), int(w),
                                          events_count=1, trade_date=td, source=source))
    n = write_stock_sentiment_snapshot(recs)
    logger.info(f"tdx 个股权重写入 {n} 条，跳过 {skipped} 条（无数据）")
    return n


# ---------------------------------------------------------------------------
# ④' 落库：板块权重（直接听板块，不走聚合）
# ---------------------------------------------------------------------------
def apply_tdx_sector_weight(board_code: str, board_name: str, sector_type: str,
                            weight: int, trade_date: Optional[str] = None) -> int:
    """板块级 tdx 权重(0-100) → sector_sentiment（直接写入，独立于聚合路径）。"""
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    score = round((int(weight) - 50) / 50.0, 4)
    rec = {
        "sector_code": board_code, "sector_name": board_name,
        "sector_type": sector_type, "trade_date": td,
        "sentiment_score": score, "heat": round(weight, 2),
        "member_count": 0, "top_stocks": [],
    }
    n = ss.upsert_sector_sentiment([rec])
    logger.info(f"tdx 板块权重写入 {board_name}({board_code}) 权重={weight} 分={score}")
    return n


# ---------------------------------------------------------------------------
# ⑤ 聚合：板块 + 全市场温度
# ---------------------------------------------------------------------------
def compute_market_sentiment(trade_date: Optional[str] = None,
                             source: Optional[str] = None) -> float:
    """由当日 stock_sentiment 汇总全市场舆情温度 → market_sentiment_daily。

    source=None 时融合全部来源（tdx + news），得到混合舆情温度；指定 source 则仅该源。
    舆情温度 = 个股情绪分均值（[-1,1]），并统计偏多/偏空/中性占比。
    Returns: sentiment_index
    """
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    from finfeed.storage.database import get_db_manager
    with get_db_manager().get_db() as c:
        if source:
            c.execute(
                "SELECT sentiment_score, sentiment_label FROM stock_sentiment "
                "WHERE trade_date = ? AND source = ?",
                (td, source),
            )
        else:
            c.execute(
                "SELECT sentiment_score, sentiment_label FROM stock_sentiment "
                "WHERE trade_date = ?",
                (td,),
            )
        rows = c.fetchall()
    if not rows:
        logger.warning(f"{td} 无 tdx 个股情绪数据，市场温度置 0")
        ss.upsert_market_sentiment(td, sentiment_index=0.0)
        return 0.0
    scores = [r["sentiment_score"] for r in rows]
    idx = round(sum(scores) / len(scores), 4)
    pos = sum(1 for r in rows if r["sentiment_label"] == "positive")
    neg = sum(1 for r in rows if r["sentiment_label"] == "negative")
    neu = len(rows) - pos - neg
    ss.upsert_market_sentiment(
        td, sentiment_index=idx,
        up_limit=pos, down_limit=neg, breadth=neu,
        forum_heat=round(sum(scores) / len(scores) * 100, 2) if scores else 0.0,
        news_sentiment=idx,
    )
    logger.info(f"市场舆情温度 {td} = {idx}（多{pos}/空{neg}/中{neu}，样本{len(rows)}）")
    return idx


def run_aggregation(trade_date: Optional[str] = None,
                    sector_type: Optional[str] = None,
                    source: str = SOURCE_NAME) -> Dict:
    """一键聚合：板块（个股→板块）+ 全市场温度（融合全部来源）。返回汇总。"""
    td = trade_date or now_bj().strftime("%Y-%m-%d")
    n_sect = build_sector_snapshot(td, sector_type=sector_type)
    idx = compute_market_sentiment(td, source=None)  # 混合 tdx + news
    return {"trade_date": td, "sectors_aggregated": n_sect, "market_index": idx}


# ---------------------------------------------------------------------------
# CLI：agent 可 `python -m finfeed.analysis.tdx_snapshot_runner --pool --top-n 150`
# ---------------------------------------------------------------------------
def _main():
    import argparse
    p = argparse.ArgumentParser(description="tdx 盘后情绪快照编排")
    p.add_argument("--pool", action="store_true", help="输出盘后目标池 JSON")
    p.add_argument("--top-n", type=int, default=150, help="人气榜取前 N")
    p.add_argument("--extra-codes", type=str, default="", help="逗号分隔额外代码")
    p.add_argument("--apply", type=str, default="", help="读取权重JSON {code:weight} 落库+聚合")
    p.add_argument("--render", action="store_true", help="输出舆情情绪板块 Markdown")
    p.add_argument("--date", type=str, default="", help="交易日 YYYY-MM-DD（默认今日）")
    p.add_argument("--source", type=str, default=SOURCE_NAME, help="情绪源标识")
    args = p.parse_args()
    td = args.date or now_bj().strftime("%Y-%m-%d")
    if args.pool:
        extra = [c.strip() for c in args.extra_codes.split(",") if c.strip()]
        pool = select_prioritized_pool(top_n=args.top_n, extra_codes=extra or None)
        # 附带 setcode，方便 agent 直接调 MCP
        for it in pool:
            it["setcode_code"] = to_tdx_setcode(it["code"])
        print(json.dumps(pool, ensure_ascii=False, indent=2))
    elif args.apply:
        with open(args.apply, "r", encoding="utf-8") as f:
            weight_map = json.load(f)
        n = apply_tdx_stock_weights(weight_map, trade_date=td, source=args.source)
        summary = run_aggregation(td, source=args.source)
        print(json.dumps({"written": n, **summary}, ensure_ascii=False))
    elif args.render:
        from finfeed.analysis.report_sentiment import render_sentiment_section
        print(render_sentiment_section(td, source=args.source))
    else:
        p.print_help()


if __name__ == "__main__":
    _main()
