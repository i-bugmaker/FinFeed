#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""股票监控模块 — 业务服务层。

职责：
- 代码规范化与有效性校验（正则 -> 板块规则 -> 行情库在线核验，easy-tdx 优先）
- 三种导入方式统一入口 ``parse_and_import``（手动 / 文本批量 / OCR 文本）
- 舆情聚合 ``aggregate_feed``（系统内 news 表实时匹配 + 系统外缓存合并分组）
- 外部消息后台刷新线程 ``RefreshWorker``（周期抓取东财资讯/公告并幂等入库，
  用户离线期间消息持续累积，重新上线经 since_ts 一次性补全）
- AI 分析任务（后台线程调用 finfeed.llm，结构化结果落库）
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from finfeed.stock_monitor import external, ocr, store
from finfeed.utils.time_utils import now_bj

logger = logging.getLogger("stock_monitor")

# 代码规范化与校验
_CODE_RE = re.compile(r"(?<![\dA-Za-z])(?:sh|sz|bj|SH|SZ|BJ)?[:.]?(\d{6})(?![\dA-Za-z])")
_PREFIXED_RE = re.compile(r"(?:sh|sz|bj)[:.]?(\d{6})", re.IGNORECASE)

# 板块规则：前缀 -> (market, board)
_BOARD_RULES: List[Tuple[str, str, str]] = [
    ("688", "SH", "科创板"),
    ("689", "SH", "科创板"),
    ("60", "SH", "主板"),
    ("00", "SZ", "主板"),
    ("30", "SZ", "创业板"),
    ("43", "BJ", "北交所"),
    ("83", "BJ", "北交所"),
    ("87", "BJ", "北交所"),
    ("92", "BJ", "北交所"),
]

# 每只股票名称解析的内存缓存，避免导入批量的重复外呼
_name_cache: Dict[str, str] = {}
_name_cache_lock = threading.Lock()


def normalize_code(raw: str) -> Optional[str]:
    """从任意输入片段提取 6 位代码（支持 sh600519 / 600519.SH / 1.600519 等写法）。"""
    s = (raw or "").strip()
    if not s:
        return None
    m = _PREFIXED_RE.search(s)
    if m:
        return m.group(1)
    m = _CODE_RE.search(s)
    if m:
        return m.group(1)
    return None


def classify_board(code: str) -> Tuple[str, str]:
    """按代码前缀推断 (market, board)；无法识别返回 ('', '')。"""
    for prefix, market, board in _BOARD_RULES:
        if code.startswith(prefix):
            return market, board
    return "", ""


def _resolve_name(code: str, market: str) -> Tuple[Optional[str], bool]:
    """解析股票名称。返回 (name|None, online_reachable)。

    解析顺序：本地 stock_meta -> easy-tdx 行情核验 -> 东方财富行情接口。
    两个在线渠道都「网络异常」时 online_reachable=False，由调用方决定降级策略。
    """
    with _name_cache_lock:
        if code in _name_cache:
            return _name_cache[code], True

    # 1) 本地库（主系统抓取与归因过程中积累的元数据）
    try:
        from finfeed.storage.database import db_get_stock_name

        name = db_get_stock_name(code)
        if name:
            with _name_cache_lock:
                _name_cache[code] = name
            return name, True
    except Exception:  # noqa: BLE001
        pass

    # 2) easy-tdx 行情核验（同步、短超时；失败自动走下一渠道）
    try:
        from easy_tdx import TdxClient

        mkt = 1 if market == "SH" else 0
        with TdxClient() as tc:
            df = tc.get_security_quotes([(mkt, code)])
        if df is not None and not df.empty:
            name = str(df.iloc[0].get("name") or "").strip()
            if name:
                with _name_cache_lock:
                    _name_cache[code] = name
                return name, True
    except Exception as e:  # noqa: BLE001
        logger.debug("easy-tdx 核验 %s 失败: %s", code, e)

    # 3) 东方财富行情接口
    try:
        r = external.resolve_name_online(code, market)
        if r:
            with _name_cache_lock:
                _name_cache[code] = r["name"]
            return r["name"], True
        return None, True  # 接口可达但明确无此代码
    except Exception as e:  # noqa: BLE001
        logger.debug("东财核验 %s 失败: %s", code, e)
        return None, False


def validate_code(raw: str) -> Dict[str, Any]:
    """校验单个代码。返回 {raw, code, market, board, name, valid, verified, reason}。"""
    out: Dict[str, Any] = {
        "raw": raw, "code": None, "market": "", "board": "",
        "name": "", "valid": False, "verified": False, "reason": "",
    }
    code = normalize_code(raw)
    if not code:
        out["reason"] = "未识别出 6 位股票代码"
        return out
    market, board = classify_board(code)
    if not market:
        out["code"] = code
        out["reason"] = "代码不符合 A 股沪深北板块规则"
        return out
    out.update({"code": code, "market": market, "board": board})
    name, reachable = _resolve_name(code, market)
    if name:
        out.update({"name": name, "valid": True, "verified": True})
        return out
    if reachable:
        out["reason"] = "行情库中不存在该代码"
        return out
    # 两个在线渠道均不可达：按格式规则放行，标记未核验
    out.update({"valid": True, "verified": False})
    out["reason"] = "行情服务不可达，已按规则放行（未在线核验）"
    return out


# 名称 / 拼音简称解析（导入支持「股票名称」「拼音缩写」两种输入）
_UNIVERSE_META_KEY = "stock_monitor_universe_synced_at"
_UNIVERSE_TTL_SEC = 7 * 86400  # 全市场名单 7 天同步一次

# 名称索引进程级缓存：{'by_name': {name: [code]}, 'by_abbr': {abbr: [code]},
#                      'code2name': {code: name}, 'built_at': ts}
_name_index: Optional[Dict[str, Any]] = None
_name_index_lock = threading.Lock()


def _norm_text(s: str) -> str:
    """名称归一化：全角转半角（NFKC）、去所有空白符，供索引键与输入匹配。"""
    import unicodedata

    return "".join(
        ch for ch in unicodedata.normalize("NFKC", s or "") if not ch.isspace()
    )


def _pinyin_abbr(name: str) -> str:
    """取名称拼音首字母缩写（如 贵州茅台 -> gzmt，万科A -> wka，TCL科技 -> tclkj）。

    非汉字字符（字母/数字）原样保留并转小写，保证带字母后缀的名称可被拼音匹配。
    """
    try:
        from pypinyin import Style, lazy_pinyin

        parts = lazy_pinyin(name, style=Style.FIRST_LETTER)
        return "".join(p for p in parts if p and not p.isspace()).lower()
    except Exception:  # noqa: BLE001  # pypinyin 未安装时降级为不支持拼音
        return ""


def _build_name_index() -> Dict[str, Any]:
    """从 stock_meta（内置映射 + 全市场同步 + 抓取积累）构建名称/拼音索引。"""
    try:
        from finfeed.storage.database import db_get_all_stock_names

        names = db_get_all_stock_names()
    except Exception as e:  # noqa: BLE001
        logger.warning("读取股票名称表失败: %s", e)
        names = {}
    by_name: Dict[str, List[str]] = {}
    by_abbr: Dict[str, List[str]] = {}
    code2name: Dict[str, str] = {}
    for code, raw_name in names.items():
        raw_name = (raw_name or "").strip()
        name = _norm_text(raw_name)
        if not name or len(code) != 6 or not code.isdigit():
            continue
        by_name.setdefault(name, []).append(code)
        code2name[code] = raw_name or name
        abbr = _pinyin_abbr(name)
        if abbr:
            by_abbr.setdefault(abbr, []).append(code)
    return {"by_name": by_name, "by_abbr": by_abbr, "code2name": code2name}


def _get_name_index() -> Dict[str, Any]:
    global _name_index
    with _name_index_lock:
        if _name_index is None:
            _name_index = _build_name_index()
        return _name_index


def _reset_name_index() -> None:
    global _name_index
    with _name_index_lock:
        _name_index = None


def _kick_universe_sync() -> None:
    """后台同步全市场 A 股名单到 stock_meta（7 天 TTL），提升名称/拼音覆盖率。"""

    def _job() -> None:
        try:
            from finfeed.storage.database import (
                db_get_metadata,
                db_set_metadata,
                db_upsert_stock_meta_full,
            )

            last = db_get_metadata(_UNIVERSE_META_KEY, "")
            if last:
                try:
                    if time.time() - float(last) < _UNIVERSE_TTL_SEC:
                        return
                except ValueError:
                    pass
            rows = external.fetch_all_a_names()
            if len(rows) < 3000:
                logger.warning("全市场名单拉取不完整（%s 条），本次跳过入库", len(rows))
                return
            stock_map: Dict[str, Dict[str, str]] = {}
            for r in rows:
                market, _ = classify_board(r["code"])
                if not market:
                    continue
                stock_map[r["code"]] = {"name": r["name"], "industry": "", "market": market}
            db_upsert_stock_meta_full(stock_map)
            db_set_metadata(_UNIVERSE_META_KEY, str(time.time()))
            _reset_name_index()
            logger.info("全市场股票名单已同步：%s 只", len(stock_map))
        except Exception as e:  # noqa: BLE001
            logger.warning("全市场名单同步失败（名称/拼音解析降级为本地映射）: %s", e)

    threading.Thread(target=_job, name="stock-universe-sync", daemon=True).start()


def _candidates_payload(codes: List[str], limit: int = 8) -> List[Dict[str, str]]:
    idx = _get_name_index()
    out: List[Dict[str, str]] = []
    for c in codes[:limit]:
        out.append({"code": c, "name": idx["code2name"].get(c, "")})
    return out


def _resolved_token(codes: List[str], matched_by: str) -> Dict[str, Any]:
    if len(codes) == 1:
        return {"code": codes[0], "matched_by": matched_by}
    return {
        "code": None,
        "ambiguous": True,
        "matched_by": matched_by,
        "candidates": _candidates_payload(codes),
    }


def resolve_token(token: str) -> Dict[str, Any]:
    """把「股票名称 / 拼音简称」解析为唯一代码。

    匹配优先级：精确名称 > 精确拼音缩写 > 名称包含（双向子串）> 拼音前缀。
    命中多只股票时返回 ambiguous + 候选列表，由调用方提示用户改用代码。
    """
    t = _norm_text(token)
    if not t:
        return {"code": None, "reason": "空输入"}
    idx = _get_name_index()

    hits = idx["by_name"].get(t)
    if hits:
        return _resolved_token(hits, "name")

    ab = t.lower()
    hits = idx["by_abbr"].get(ab)
    if hits:
        return _resolved_token(hits, "pinyin")

    if len(t) < 2:
        return {"code": None, "reason": "输入过短，无法唯一识别（请输入全称或完整拼音缩写）"}

    # 名称包含匹配（如「茅台」-> 贵州茅台；也容忍名称带前后缀的输入）
    sub: List[str] = []
    for name, codes in idx["by_name"].items():
        if t in name or name in t:
            sub.extend(codes)
    if sub:
        return _resolved_token(sub, "name")

    # 拼音前缀匹配（如 gzmt / gzm）
    pref: List[str] = []
    for a, codes in idx["by_abbr"].items():
        if a.startswith(ab):
            pref.extend(codes)
    if pref:
        return _resolved_token(pref, "pinyin")

    return {"code": None, "reason": "未匹配到股票名称或拼音简称（可尝试完整名称 / 6 位代码）"}


def suggest_stocks(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """导入框智能联想：按代码前缀 / 名称 / 拼音简称即时匹配，按匹配质量排序。"""
    idx = _get_name_index()
    t = _norm_text(query).lower()
    if not t:
        return []
    scored: Dict[str, int] = {}

    def _add(codes: List[str], score: int) -> None:
        for c in codes:
            if c not in scored or scored[c] > score:
                scored[c] = score

    if t.isdigit():
        _add([c for c in idx["code2name"] if c.startswith(t)], 0)   # 代码前缀
    if t in idx["by_name"]:
        _add(idx["by_name"][t], 0)          # 名称精确
    if t in idx["by_abbr"]:
        _add(idx["by_abbr"][t], 1)          # 拼音精确
    for name, codes in idx["by_name"].items():
        if t in name:
            _add(codes, 2)                  # 名称包含
    for abbr, codes in idx["by_abbr"].items():
        if abbr.startswith(t):
            _add(codes, 3)                  # 拼音前缀
    for abbr, codes in idx["by_abbr"].items():
        if abbr.find(t) > 0:
            _add(codes, 4)                  # 拼音包含

    ranked = sorted(scored.items(), key=lambda kv: (kv[1], kv[0]))[:limit]
    out: List[Dict[str, Any]] = []
    for code, score in ranked:
        market, board = classify_board(code)
        out.append({
            "code": code,
            "name": idx["code2name"].get(code, ""),
            "market": market,
            "board": board,
            "score": score,
        })
    return out


# 导入（手动 / 文本批量 / OCR）
def parse_and_import(text: str) -> Dict[str, Any]:
    """从文本解析并批量导入监控列表。

    每个分词依次尝试：6 位代码（含 sh/sz 前缀等写法）-> 股票名称 ->
    拼音简称（含前缀模糊）。名称/拼音命中多只股票时返回候选不导入。
    """
    store.ensure_tables()
    _kick_universe_sync()  # 首次使用触发全市场名单后台同步（7 天一次）
    tokens = re.split(r"[\s,，;；、|]+", (text or "").strip())
    seen: set = set()
    results: List[Dict[str, Any]] = []
    added = 0
    duplicates = 0
    for tok in tokens:
        if not tok:
            continue
        code = normalize_code(tok)
        matched_by = "code"
        if not code:
            r = resolve_token(tok)
            if r.get("ambiguous"):
                cand = "、".join(
                    f"{c['code']} {c['name']}" for c in (r.get("candidates") or [])
                )
                results.append({
                    "raw": tok,
                    "valid": False,
                    "reason": f"「{tok}」匹配到多只股票：{cand}，请用代码精确导入",
                    "candidates": r.get("candidates") or [],
                })
                continue
            if not r.get("code"):
                results.append({
                    "raw": tok,
                    "valid": False,
                    "reason": r.get("reason") or "未识别出股票代码、名称或拼音简称",
                })
                continue
            code = r["code"]
            matched_by = r.get("matched_by", "name")
        if code in seen:
            continue
        seen.add(code)
        v = validate_code(code)
        v["raw"] = tok
        if matched_by != "code":
            v["matched_by"] = matched_by
            if not v.get("name"):
                v["name"] = _get_name_index()["code2name"].get(code, "")
        if not v["valid"]:
            results.append(v)
            continue
        existing = store.get_stock(code)
        if existing:
            duplicates += 1
            # 已存在时顺带补齐名称/板块元数据
            store.upsert_stock(code, v.get("name", ""), v["market"], v["board"], existing.get("note", ""))
            results.append({**v, "duplicate": True})
            continue
        store.upsert_stock(code, v.get("name", ""), v["market"], v["board"])
        added += 1
        results.append(v)
        # 新导入立即拉一轮外部消息，保证打开详情即有数据
        threading.Thread(
            target=_refresh_codes_safely, args=([{"code": code, "market": v["market"]}],),
            daemon=True,
        ).start()
    return {
        "added": added,
        "duplicates": duplicates,
        "results": results,
        "stocks": store.list_stocks(),
    }


def import_image(data: bytes) -> Dict[str, Any]:
    """截图批量导入：OCR 提取文本 -> parse_and_import。"""
    r = ocr.extract_text(data)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error") or r.get("hint", "OCR 识别失败")}
    text = "\n".join(r.get("lines") or [])
    if not normalize_code(text):
        return {"ok": False, "error": "截图中未识别出股票代码，请确认截图内容"}
    imported = parse_and_import(text)
    return {"ok": True, "engine": r.get("engine", ""), "text": text, **imported}


# 外部消息刷新
REFRESH_INTERVAL_SEC = int(os.environ.get("FINFEED_WATCH_REFRESH_SEC", "300"))


def _refresh_codes_safely(entries: List[Dict[str, str]]) -> int:
    try:
        items = external.fetch_all_for_codes(entries)
        return store.insert_external_messages(items)
    except Exception as e:  # noqa: BLE001
        logger.warning("外部消息刷新失败: %s", e)
        return 0


class RefreshWorker:
    """后台线程：周期为全部监控股票拉取外部资讯/公告（幂等入库）。

    用户离线期间线程照常运行，消息持续累积在 stock_messages；
    前端重新上线后以 since_ts（localStorage 记忆的 last_seen_ts）
    调用 /feed 即可一次性补全遗漏消息。
    """

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.last_refresh_ts: float = 0.0
        self.last_refresh_count: int = 0
        self.last_error: str = ""

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="stock-monitor-refresh", daemon=True)
            self._thread.start()
            logger.info("股票监控外部消息刷新线程已启动（间隔 %ss）", REFRESH_INTERVAL_SEC)

    def stop(self) -> None:
        self._stop.set()

    def refresh_now(self) -> Dict[str, Any]:
        """立即刷新一轮（供手动触发接口）。"""
        entries = [
            {"code": s["code"], "market": s.get("market", "")}
            for s in store.list_stocks()
        ]
        n = _refresh_codes_safely(entries)
        self.last_refresh_ts = time.time()
        self.last_refresh_count = n
        return {"codes": len(entries), "inserted": n}

    def _run(self) -> None:
        # 启动即先刷一轮，随后周期执行
        while not self._stop.is_set():
            try:
                r = self.refresh_now()
                self.last_error = ""
                logger.info("外部舆情刷新完成: %s", r)
            except Exception as e:  # noqa: BLE001
                self.last_error = str(e)
                logger.warning("外部舆情刷新异常: %s", e)
            self._stop.wait(REFRESH_INTERVAL_SEC)


worker = RefreshWorker()


# 舆情聚合
def _watched_entries(codes: Optional[List[str]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    stocks = store.list_stocks()
    if codes:
        wanted = set(codes)
        stocks = [s for s in stocks if s["code"] in wanted]
    return stocks, [s["code"] for s in stocks]


def aggregate_feed(
    codes: Optional[List[str]] = None,
    since_ts: int = 0,
    limit_per_code: int = 60,
) -> Dict[str, Any]:
    """聚合每只监控股票的舆情：系统内（news 实时匹配）+ 系统外（缓存）。

    返回 {"groups": {code: {"stock": {...}, "items": [...], "counts": {...}}}, "server_ts"}。
    items 统一结构：{source_type, channel, title, url, summary, source,
                    publish_time, publish_ts, sentiment?, importance?}。
    """
    stocks, code_list = _watched_entries(codes)
    names = {s["code"]: s.get("name", "") for s in stocks}
    groups: Dict[str, Dict[str, Any]] = {}

    internal_all: List[Dict[str, Any]] = []
    if code_list:
        internal_all = store.get_internal_messages(code_list, names, since_ts=since_ts)
    internal_by_code: Dict[str, List[Dict[str, Any]]] = {c: [] for c in code_list}
    for it in internal_all:
        for c in it.get("codes") or []:
            if c in internal_by_code:
                internal_by_code[c].append(it)

    external_all = store.get_external_messages(code_list, since_ts=since_ts, limit=100000)
    external_by_code: Dict[str, List[Dict[str, Any]]] = {c: [] for c in code_list}
    for it in external_all:
        external_by_code.setdefault(it["code"], []).append(it)

    server_now = now_bj().timestamp().__int__()
    for s in stocks:
        code = s["code"]
        items: List[Dict[str, Any]] = []
        for it in internal_by_code.get(code, [])[:limit_per_code]:
            items.append({
                "source_type": "internal",
                "channel": it.get("category") or "news",
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "summary": it.get("intro", ""),
                "source": it.get("source", ""),
                "publish_time": it.get("publish_time", ""),
                "publish_ts": it.get("publish_ts", 0),
                "sentiment": it.get("sentiment", ""),
                "importance": it.get("importance", 0),
                "ref_id": it.get("id"),
            })
        for it in external_by_code.get(code, [])[:limit_per_code]:
            items.append({
                "source_type": "external",
                "channel": it.get("channel") or "news",
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "summary": it.get("summary", ""),
                "source": it.get("source", ""),
                "publish_time": it.get("publish_time", ""),
                "publish_ts": it.get("publish_ts", 0),
                "ref_id": it.get("id"),
            })
        items.sort(key=lambda d: (d.get("publish_ts") or 0), reverse=True)
        counts = {
            "total": len(items),
            "internal": sum(1 for i in items if i["source_type"] == "internal"),
            "external": sum(1 for i in items if i["source_type"] == "external"),
            "announcement": sum(1 for i in items if i.get("channel") == "announcement"),
        }
        groups[code] = {"stock": s, "items": items[:limit_per_code], "counts": counts}

    return {
        "groups": groups,
        "server_ts": server_now,
        "watch_total": len(store.list_stocks()),
    }


def realtime_new_items(codes: List[str], last_internal_id: int, last_external_id: int) -> Dict[str, Any]:
    """SSE 轮询用：返回自水位线以来两路（系统内/外）新增消息（跨股票平铺）。"""
    stocks, code_list = _watched_entries(codes)
    if not code_list:
        return {"items": [], "internal_watermark": last_internal_id, "external_watermark": last_external_id}
    names = {s["code"]: s.get("name", "") for s in stocks}
    try:
        from finfeed.storage.database import db_get_max_news_id

        cur_internal_max = db_get_max_news_id()
    except Exception:  # noqa: BLE001
        cur_internal_max = last_internal_id

    items: List[Dict[str, Any]] = []
    new_internal_max = last_internal_id
    if cur_internal_max > last_internal_id:
        for it in store.get_internal_messages(code_list, names, after_id=last_internal_id, limit=100):
            for c in it.get("codes") or []:
                items.append({
                    "code": c,
                    "source_type": "internal",
                    "channel": it.get("category") or "news",
                    "title": it.get("title", ""),
                    "url": it.get("url", ""),
                    "summary": it.get("intro", ""),
                    "source": it.get("source", ""),
                    "publish_time": it.get("publish_time", ""),
                    "publish_ts": it.get("publish_ts", 0),
                })
        new_internal_max = cur_internal_max

    ext_items = store.get_external_messages(code_list, after_id=last_external_id, limit=100)
    new_external_max = last_external_id
    for it in ext_items:
        new_external_max = max(new_external_max, int(it.get("id") or 0))
        items.append({
            "code": it["code"],
            "source_type": "external",
            "channel": it.get("channel") or "news",
            "title": it.get("title", ""),
            "url": it.get("url", ""),
            "summary": it.get("summary", ""),
            "source": it.get("source", ""),
            "publish_time": it.get("publish_time", ""),
            "publish_ts": it.get("publish_ts", 0),
        })

    items.sort(key=lambda d: d.get("publish_ts") or 0, reverse=True)
    return {
        "items": items[:80],
        "internal_watermark": new_internal_max,
        "external_watermark": new_external_max,
    }


# AI 智能分析
_ANALYSIS_MSG_LIMIT = 40  # 参与单次分析的最大消息条数


def _build_analysis_context(code: str) -> Tuple[str, int, Optional[str]]:
    """构建分析上下文文本。返回 (context_text, msg_count, stock_name)。"""
    feed = aggregate_feed([code], since_ts=0, limit_per_code=_ANALYSIS_MSG_LIMIT)
    group = (feed.get("groups") or {}).get(code) or {}
    stock = group.get("stock") or {}
    name = stock.get("name") or code
    items = group.get("items") or []
    if not items:
        return "", 0, name
    lines = []
    for i, it in enumerate(items, 1):
        src = "系统内" if it.get("source_type") == "internal" else "系统外"
        ch = {"announcement": "公告", "news": "资讯", "flash": "快讯",
              "article": "财经", "forum": "舆情"}.get(it.get("channel"), it.get("channel"))
        senti = it.get("sentiment") or ""
        line = f"{i}. [{src}|{ch}] ({it.get('publish_time', '')}) {it.get('title', '')}"
        if senti and senti != "neutral":
            line += f" [情绪:{senti}]"
        summary = (it.get("summary") or "").strip()
        if summary:
            line += f" — {summary[:160]}"
        lines.append(line)
    ctx = "\n".join(lines)
    return ctx, len(items), name


_ANALYSIS_PROMPT = """你是一名 A 股卖方分析师。以下是监控股票「{name}（{code}）」聚合的近期舆情消息
（覆盖系统内抓取的快讯/财经/舆情与系统外公告/资讯，按时间倒序）：

{context}

请基于以上消息完成智能分析，**严格输出以下 JSON（不要输出任何 JSON 之外的内容）**：
{{
  "sentiment": "利好 或 利空 或 中性",
  "impact": "高 或 中 或 低",
  "summary": "一句话总体结论（60 字以内）",
  "key_points": ["关键消息解读 1", "关键消息解读 2", "...（3-6 条）"],
  "analysis": "完整分析（Markdown，300-600 字）：包含消息面解读、情绪倾向及依据、对股价/基本面的影响评估、需要跟踪的后续事件与风险提示"
}}

要求：区分事实与观点；情绪判断需给出消息依据；不得虚构消息中不存在的信息；若消息量过少请如实说明分析局限性。"""


def submit_analysis(code: str) -> Dict[str, Any]:
    """提交一次 AI 分析（后台线程执行）。返回任务信息或错误。"""
    stock = store.get_stock(code)
    if not stock:
        return {"ok": False, "error": f"股票 {code} 不在监控列表中"}
    try:
        from finfeed.llm.config import get_default_provider

        provider = get_default_provider()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"读取 LLM 配置失败: {e}"}
    if provider is None:
        return {
            "ok": False,
            "error": "尚未配置 LLM 供应商，请先在「AI 投研 → 设置」中配置后重试",
        }
    analysis_id = store.create_analysis(code)
    threading.Thread(target=_run_analysis, args=(analysis_id, code, stock), daemon=True).start()
    return {"ok": True, "analysis_id": analysis_id, "code": code, "status": "running"}


def _run_analysis(analysis_id: int, code: str, stock: Dict[str, Any]) -> None:
    try:
        context, msg_count, name = _build_analysis_context(code)
        if msg_count == 0:
            store.fail_analysis(analysis_id, "暂无该股票的舆情消息，无法分析（可先手动刷新外部消息）")
            return

        from finfeed.llm.client import build_client
        from finfeed.llm.config import get_default_provider

        provider = get_default_provider()
        client = build_client(provider)
        prompt = _ANALYSIS_PROMPT.format(name=name or code, code=code, context=context)
        result = client.chat(
            [
                {"role": "system", "content": "你是严谨的 A 股舆情分析师，只输出被要求的 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        content = result.content or ""
        parsed = _parse_analysis_json(content)
        store.finish_analysis(
            analysis_id,
            content=parsed.get("analysis") or content,
            sentiment=parsed.get("sentiment", ""),
            impact=parsed.get("impact", ""),
            model=getattr(result, "model", "") or getattr(provider, "model", ""),
            msg_count=msg_count,
        )
        logger.info("股票 %s AI 分析完成 (analysis_id=%s, msgs=%s)", code, analysis_id, msg_count)
    except Exception as e:  # noqa: BLE001
        logger.exception("股票 %s AI 分析失败", code)
        store.fail_analysis(analysis_id, str(e))


def _parse_analysis_json(text: str) -> Dict[str, Any]:
    """尽力从模型输出提取 JSON（容忍 ```json 代码块包裹）。"""
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.DOTALL)
    if m:
        t = m.group(1)
    else:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            t = t[start:end + 1]
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# 模块状态
def module_status() -> Dict[str, Any]:
    stocks = store.list_stocks()
    return {
        "watch_total": len(stocks),
        "refresh_interval_sec": REFRESH_INTERVAL_SEC,
        "last_refresh_ts": worker.last_refresh_ts,
        "last_refresh_count": worker.last_refresh_count,
        "worker_running": bool(worker._thread and worker._thread.is_alive()),  # noqa: SLF001
        "ocr_hint": ocr._INSTALL_HINT,  # noqa: SLF001
    }
