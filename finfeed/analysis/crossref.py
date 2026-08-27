#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新闻 × 行情 交叉分析层

三大能力（对应升级方案 场景1 / 场景3）：
1. 实体识别增强：基于全量 stock_meta 构建 Aho-Corasick 自动机 + 别名词典，
   从「贵州茅台涨停」这类不含代码的新闻中识别个股，写入 news_stock_link。
2. 历史回填：对 13.3 万条历史新闻批量重跑，生成 news_stock_link，为回测备料。
3. 情感闭环校准：以新闻关联个股的 T+1 收盘涨跌幅为真值，量化各情感标签 /
   各新闻源的真实胜率与平均收益（IC）。

本模块不侵入抓取热路径；回填与校准均为离线批处理。
"""

import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from finfeed.analysis.text_analyzer import extract_stock_codes
from finfeed.market import store as market_store
from finfeed.storage.database import get_db_manager

logger = logging.getLogger("news_monitor")

# 6 位代码（带/不带后缀）兜底匹配
_CODE_RE = re.compile(r"(?<!\d)(60\d{4}|688\d{3}|00\d{4}|30\d{4})(?!\d)")
_CODE_SECURE = re.compile(r"\b(60\d{4}|688\d{3}|00\d{4}|30\d{4})\.(SH|SZ|sh|sz)\b")


# ---------------------------------------------------------------------------
# Aho-Corasick 自动机（纯 Python，无第三方依赖）
# ---------------------------------------------------------------------------
class _ACNode:
    __slots__ = ("goto", "fail", "output")

    def __init__(self):
        self.goto: Dict[str, "_ACNode"] = {}
        self.fail: Optional["_ACNode"] = None
        self.output: Set[str] = set()


class EntityRecognizer:
    """股票名称/别名 -> 代码 多模式匹配。"""

    def __init__(self) -> None:
        self.root = _ACNode()
        self._built = False

    def build_from_stock_meta(self) -> int:
        """从 stock_meta 载入名称 + 别名，构建自动机。返回模式串数量。"""
        db = get_db_manager()
        with db.get_db() as c:
            c.execute("SELECT code, name, alias FROM stock_meta WHERE name IS NOT NULL AND name != ''")
            rows = c.fetchall()
        pattern_count = 0
        for r in rows:
            code = r["code"]
            names = set()
            if r["name"]:
                names.add(r["name"].strip())
            try:
                for a in (r["alias"] or "[]"):
                    if isinstance(a, str) and a:
                        names.add(a.strip())
            except Exception:  # noqa: BLE001
                pass
            for nm in names:
                if len(nm) >= 2:
                    self._add(nm, code)
                    pattern_count += 1
        self._build_fail()
        self._built = True
        logger.info(f"实体识别自动机构建完成：{pattern_count} 个模式串 / {len(rows)} 只股票")
        return pattern_count

    def _add(self, word: str, code: str) -> None:
        node = self.root
        for ch in word:
            if ch not in node.goto:
                node.goto[ch] = _ACNode()
            node = node.goto[ch]
        node.output.add(code)

    def _build_fail(self) -> None:
        from collections import deque
        q: deque = deque()
        for child in self.root.goto.values():
            child.fail = self.root
            q.append(child)
        while q:
            r = q.popleft()
            for ch, w in r.goto.items():
                q.append(w)
                f = r.fail
                while f is not None and ch not in f.goto:
                    f = f.fail
                w.fail = f.goto[ch] if (f is not None and ch in f.goto) else self.root

    def find(self, text: str) -> Dict[str, str]:
        """返回 {code: matched_name}（取最长/首个命中）。"""
        if not self._built or not text:
            return {}
        result: Dict[str, str] = {}
        node = self.root
        for i, ch in enumerate(text):
            while node is not None and ch not in node.goto:
                node = node.fail
            if node is None:
                node = self.root
                continue
            node = node.goto[ch]
            for code in node.output:
                # 记录命中（按首次出现顺序，去重）
                result[code] = ch
        return result


# 模块级单例
_RECOGNIZER: Optional[EntityRecognizer] = None


def get_recognizer() -> EntityRecognizer:
    global _RECOGNIZER
    if _RECOGNIZER is None:
        _RECOGNIZER = EntityRecognizer()
        _RECOGNIZER.build_from_stock_meta()
    return _RECOGNIZER


# ---------------------------------------------------------------------------
# 单条新闻实体抽取
# ---------------------------------------------------------------------------
def extract_entities(text: str) -> List[Tuple[str, str, float]]:
    """返回 [(code, match_type, confidence)]。merge 代码正则 + 名称自动机。"""
    if not text:
        return []
    found: Dict[str, Tuple[str, float]] = {}

    # 1) 代码正则（高置信）
    for m in _CODE_SECURE.finditer(text):
        code = m.group(1)
        found[code] = ("code", 1.0)
    for m in _CODE_RE.finditer(text):
        code = m.group(1)
        if code not in found:
            found[code] = ("code", 0.9)

    # 2) 名称自动机
    rec = get_recognizer()
    for code in rec.find(text).keys():
        if code not in found:
            found[code] = ("name", 0.85)

    # 3) 旧正则（兼容）
    for item in extract_stock_codes(text):
        code = item.get("code")
        if code and code not in found:
            found[code] = ("alias", 0.7)

    return [(code, mt, conf) for code, (mt, conf) in found.items()]


def enrich_news_stocks(news_id: int, title: str, intro: str = "") -> int:
    """抽取单条新闻的个股关联并写入 news_stock_link。返回写入条数。"""
    ents = extract_entities(f"{title} {intro}")
    if not ents:
        return 0
    rows = [(news_id, code, mt, conf) for code, mt, conf in ents]
    return market_store.upsert_news_stock_link(rows)


# ---------------------------------------------------------------------------
# 历史回填
# ---------------------------------------------------------------------------
def backfill_news_stock_link(batch: int = 2000) -> int:
    """对历史新闻批量回填 news_stock_link。返回累计写入条数。"""
    db = get_db_manager()
    total = 0
    offset = 0
    while True:
        with db.get_db() as c:
            c.execute(
                "SELECT id, title, intro FROM news ORDER BY id LIMIT ? OFFSET ?",
                (batch, offset),
            )
            rows = c.fetchall()
        if not rows:
            break
        for r in rows:
            total += enrich_news_stocks(r["id"], r["title"] or "", r["intro"] or "")
        offset += batch
        if len(rows) < batch:
            break
    logger.info(f"news_stock_link 回填完成，累计关联 {total} 条")
    return total


# ---------------------------------------------------------------------------
# 情感闭环校准（T+1 回测）
# ---------------------------------------------------------------------------
def calibrate_sentiment(lookback_days: int = 180) -> Dict:
    """以关联个股 T+1 收盘涨跌幅为真值，校准情感标签与各新闻源。

    Returns: {by_label: {...}, by_source: {...}, sample: int}
    """
    db = get_db_manager()
    # 关联新闻（带发布时间、情感、源、个股）
    with db.get_db() as c:
        c.execute(
            """SELECT l.news_id, n.sentiment, n.source, n.publish_ts, l.code
               FROM news_stock_link l JOIN news n ON n.id = l.news_id
               WHERE n.publish_ts > 0"""
        )
        links = c.fetchall()
    if not links:
        return {"by_label": {}, "by_source": {}, "sample": 0, "note": "无 news_stock_link，请先回填"}

    # 预载各关联 code 的日线 {date: pct_chg}
    codes = {r["code"] for r in links}
    bar_map: Dict[str, Dict[str, float]] = {}
    all_dates: Set[str] = set()
    with db.get_db() as c:
        for code in codes:
            c.execute(
                "SELECT trade_date, pct_chg FROM daily_bar WHERE code = ? AND fq_type = 1",
                (code,),
            )
            d = {row["trade_date"]: row["pct_chg"] for row in c.fetchall()}
            if d:
                bar_map[code] = d
                all_dates.update(d.keys())

    def next_trade_date(pub_ts: int) -> Optional[str]:
        import datetime
        base = datetime.datetime.utcfromtimestamp(pub_ts) + datetime.timedelta(days=1)
        for _ in range(6):
            cand = base.strftime("%Y-%m-%d")
            if cand in all_dates:
                return cand
            base += datetime.timedelta(days=1)
        return None

    by_label = defaultdict(lambda: {"n": 0, "ret_sum": 0.0, "win": 0})
    by_source = defaultdict(lambda: {"n": 0, "ret_sum": 0.0, "win": 0})
    sample = 0
    for r in links:
        code = r["code"]
        bars = bar_map.get(code)
        if not bars:
            continue
        td = next_trade_date(r["publish_ts"])
        if not td:
            continue
        pct = bars.get(td)
        if pct is None:
            continue
        sample += 1
        lab = (r["sentiment"] or "neutral")
        s = by_label[lab]
        s["n"] += 1
        s["ret_sum"] += pct
        s["win"] += 1 if pct > 0 else 0
        src = (r["source"] or "unknown")
        s2 = by_source[src]
        s2["n"] += 1
        s2["ret_sum"] += pct
        s2["win"] += 1 if pct > 0 else 0

    def finalize(d):
        return {
            k: {
                "n": v["n"],
                "avg_ret": round(v["ret_sum"] / v["n"], 4) if v["n"] else 0.0,
                "win_rate": round(v["win"] / v["n"], 4) if v["n"] else 0.0,
            }
            for k, v in d.items()
        }

    return {
        "by_label": finalize(by_label),
        "by_source": finalize(by_source),
        "sample": sample,
    }


def run_backfill() -> int:
    return backfill_news_stock_link()


def run_calibrate(lookback_days: int = 180) -> Dict:
    return calibrate_sentiment(lookback_days)
