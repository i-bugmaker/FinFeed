"""Web 共享运行时：FastAPI 新后端与 legacy HTTP 服务共用的状态与纯函数。

为什么需要这个模块
------------------
``finfeed.ui.web.server``（legacy 双栈 HTTP 服务）与 ``finfeed.ui.web_fastapi``
（FastAPI 新后端）双轨并行，但以下状态必须保持**进程内唯一实例**：

- **SSE 广播通道**（``_sse_clients`` / 分类水位线 / tick 哨兵）：monitor 主进程
  广播的新数据必须送达 FastAPI 进程注册的浏览器 SSE 客户端；
- **API 缓存**（``_api_cache``）：两端共享同一缓存实例，避免数据口径不一致；
- **Web 运行状态**（``_web_state``）：``/api/stats`` 展示的运行态；
- **来源展示名缓存**：舆情/快讯/文章三类的来源名，两端共用同一份构建结果。

本模块收敛上述共享符号：legacy server 从本模块导入（自身行为不变），
新后端直接依赖本模块——从而解除新后端对 legacy HTTP 服务的耦合，
为 legacy 的最终退役收敛耦合面。
"""

import logging
import os
import queue
import threading
import time
from typing import Dict, Optional

from finfeed.config.settings import API_CACHE_TTL, get_display_name
from finfeed.config.sources import get_article_sources, get_flash_sources, get_forum_sources
from finfeed.storage.database import db_get_max_news_id, db_get_news_after_id, db_get_statistics
from finfeed.storage.models import NewsItem
from finfeed.utils.time_utils import now_bj, ts_from_bj_str

logger = logging.getLogger("news_monitor")

# ----------------- Web 运行状态（/api/stats 展示） -----------------
_web_state = {
    "news": [],
    "stats": {},
    "cycle": 0,
    "total": 0,
    "new_count": 0,
    "status": "启动中",
    "sources": [],
    "last_update": "",
    "server_ts": time.time(),
}
_web_state_lock = threading.Lock()

# ----------------- SSE 广播通道 -----------------
_sse_clients: set = set()
_sse_clients_lock = threading.Lock()

# 按分类独立维护水位线，避免三条流（快讯 flash / 文章 article / 舆情 forum）互相污染。
BROADCAST_CATEGORIES = ("flash", "article", "forum")
# 单次 SSE 事件携带的条目上限；超出时置 truncated=True，由前端整表刷新
SSE_MAX_ITEMS_PER_EVENT = 50
# 单轮从数据库拉取的增量上限；剩余部分下一轮继续（水位线只推进到已发送的最大 id）
BROADCAST_BATCH_LIMIT = 500
# 每个 SSE 客户端队列的上限，防止慢客户端把内存拖爆（无界队列会使死连接检测失效）
SSE_CLIENT_QUEUE_MAXSIZE = 256

_broadcast_watermarks: Dict[str, int] = {c: 0 for c in BROADCAST_CATEGORIES}
_broadcast_lock = threading.RLock()
_watermark_initialized = False

# SSE 跨进程触发哨兵（tick 文件）：
# monitor 运行在主进程，浏览器 SSE 连接注册在 FastAPI 进程的 ``_sse_clients``。
# 主进程抓取完成后「触碰」哨兵文件，FastAPI 监听到 mtime 变化即立即触发
# broadcast_new_news()，推送延迟降到亚秒级。
_SSE_TICK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".finfeed_sse_tick",
)
# 最近一次「实际广播出数据」的时间戳，供 /api/sse/health 上报，用于诊断桥接是否存活。
_last_broadcast_ts = 0.0

# ----------------- 来源展示名缓存 -----------------
_forum_source_raw_names: Optional[list] = None
_forum_source_raw_set: Optional[set] = None
_forum_source_display_names: Optional[list] = None
_forum_source_display_set: Optional[set] = None
_finance_source_display_names: Optional[list] = None
_flash_source_display_names: Optional[list] = None
_article_source_display_names: Optional[list] = None
_sources_cache_lock = threading.Lock()

# ----------------- API 缓存 -----------------
_api_cache = {}
_api_cache_lock = threading.Lock()


def touch_sse_tick() -> None:
    """通知 FastAPI 子进程：主进程已产生新数据，请立即推送。

    跨进程、进程安全的轻量信号——只更新一个文件的 mtime，开销可忽略。
    """
    try:
        os.utime(_SSE_TICK_PATH, None)
    except FileNotFoundError:
        try:
            with open(_SSE_TICK_PATH, "a"):
                pass
            os.utime(_SSE_TICK_PATH, None)
        except OSError:
            pass
    except OSError:
        pass


def get_sse_tick_mtime() -> float:
    """返回 tick 文件 mtime（秒，含小数）；文件不存在返回 0.0。"""
    try:
        return os.path.getmtime(_SSE_TICK_PATH)
    except OSError:
        return 0.0


def _cache_get(key: str):
    with _api_cache_lock:
        entry = _api_cache.get(key)
        if entry and time.time() - entry[0] < API_CACHE_TTL:
            return entry[1]
        if key in _api_cache:
            del _api_cache[key]
        return None


def _cache_set(key: str, value):
    with _api_cache_lock:
        _api_cache[key] = (time.time(), value)


def invalidate_api_cache():
    with _api_cache_lock:
        _api_cache.clear()


def invalidate_sources_cache():
    """重置来源列表缓存"""
    global _forum_source_raw_names, _forum_source_raw_set, _forum_source_display_names, _forum_source_display_set, _finance_source_display_names
    with _sources_cache_lock:
        _forum_source_raw_names = None
        _forum_source_raw_set = None
        _forum_source_display_names = None
        _forum_source_display_set = None
        _finance_source_display_names = None


def _build_categorized_sources() -> None:
    """一次性构建 flash / article / forum 三类的展示名缓存与兼容的 finance 并集。"""
    global _forum_source_raw_names, _forum_source_raw_set, _forum_source_display_names
    global _forum_source_display_set, _finance_source_display_names
    global _flash_source_display_names, _article_source_display_names
    forum_sources = get_forum_sources()
    _forum_source_raw_names = [s.name for s in forum_sources]
    _forum_source_raw_set = set(_forum_source_raw_names)
    _forum_source_display_names = list(dict.fromkeys(
        get_display_name(s.name) for s in forum_sources
    ))
    _forum_source_display_set = set(_forum_source_display_names)
    _flash_source_display_names = list(dict.fromkeys(
        get_display_name(s.name) for s in get_flash_sources()
    ))
    _article_source_display_names = list(dict.fromkeys(
        get_display_name(s.name) for s in get_article_sources()
    ))
    # 兼容语义：finance 展示名 = flash + article 展示名并集（去重保序）
    _finance_source_display_names = list(dict.fromkeys(
        _flash_source_display_names + _article_source_display_names
    ))


def _get_cached_sources():
    """返回缓存的来源集合元组（首次调用时构建）。

    返回 (forum_raw_names, forum_raw_set, forum_display_names, forum_display_set,
           finance_display_names)：
      - forum_* 为舆情论坛源的内部名/展示名
      - finance_display_names 语义保持不变（= 非论坛源的展示名去重并集），
        兼容历史调用方（FastAPI 适配层等）。
    """
    global _forum_source_raw_names, _forum_source_raw_set, _forum_source_display_names, _forum_source_display_set, _finance_source_display_names
    with _sources_cache_lock:
        if _forum_source_raw_names is None:
            _build_categorized_sources()
        return _forum_source_raw_names, _forum_source_raw_set, _forum_source_display_names, _forum_source_display_set, _finance_source_display_names


def _get_flash_article_display_names():
    """返回 (flash_display_names, article_display_names)。"""
    with _sources_cache_lock:
        if _flash_source_display_names is None:
            _build_categorized_sources()
        return _flash_source_display_names, _article_source_display_names


def _ts_from_date_str(date_str: str, end_of_day: bool = False) -> Optional[int]:
    if not date_str:
        return None
    try:
        if len(date_str) == 10:
            return ts_from_bj_str(date_str + (" 23:59:59" if end_of_day else " 00:00:00"))
        return ts_from_bj_str(date_str)
    except Exception as e:
        logger.debug(f"日期解析失败 '{date_str}': {e}")
        return None


def _build_news_response(news_items: list, total: int, offset: int, limit: int, sources: list) -> dict:
    # 列表接口不携带正文，保持响应轻量；正文通过 /api/detail 按需获取
    news_dicts = []
    for n in news_items:
        d = n.to_dict()
        d.pop("content", None)
        news_dicts.append(d)
    stats = db_get_statistics()
    has_more = len(news_items) >= limit
    next_offset = offset + len(news_items) if has_more else None

    return {
        "news": news_dicts,
        "total": total,
        "offset": offset,
        "next_offset": next_offset,
        "limit": limit,
        "returned_count": len(news_items),
        "has_more": has_more,
        "stats": stats,
        "sources": sources,
        "server_ts": time.time(),
    }


def _drain_queue(q: queue.Queue) -> None:
    """清空队列中的积压消息（用于慢客户端降级）"""
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            break


def _sse_broadcast(message: dict):
    with _sse_clients_lock:
        client_count = len(_sse_clients)
        for q in _sse_clients:
            try:
                q.put_nowait(message)
            except queue.Full:
                # 慢客户端：丢弃积压并投递一条「截断」通知，
                # 让前端整表刷新而不是静默丢消息（此前无界队列 + 直接踢掉
                # 客户端，会让该连接变成收不到任何更新的僵尸连接）。
                _drain_queue(q)
                try:
                    q.put_nowait({
                        "type": "new_news",
                        "category": message.get("category", "finance"),
                        "items": [],
                        "count": message.get("count", 0),
                        "truncated": True,
                        "ts": time.time(),
                    })
                except queue.Full:
                    logger.warning("SSE 客户端队列持续拥塞，已跳过本次投递")
        if client_count > 0:
            logger.info(
                f"SSE广播: {client_count} 客户端, 消息类型: {message.get('type')}, "
                f"数量: {message.get('count', 0)}"
            )


def init_broadcast_watermark() -> None:
    """把增量推送水位线对齐到库内当前最大 id。

    必须在 Web 服务启动时调用一次，否则首轮 broadcast_new_news() 会把
    整个历史库当作「新增」全量广播出去。
    """
    global _watermark_initialized
    with _broadcast_lock:
        for cat in BROADCAST_CATEGORIES:
            try:
                _broadcast_watermarks[cat] = db_get_max_news_id(cat)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"初始化 {cat} 推送水位线失败，按 0 处理: {e}")
                _broadcast_watermarks[cat] = 0
        _watermark_initialized = True
        logger.info(f"SSE 推送水位线已初始化: {dict(_broadcast_watermarks)}")


def broadcast_new_news(batch_limit: int = BROADCAST_BATCH_LIMIT) -> Dict[str, int]:
    """按自增 id 水位线拉取未推送的新闻并广播 SSE —— 增量推送的唯一权威入口。

    设计要点：
    1. **数据来源自持**。调用方只需说「可能有新数据了」，不需要（也不应该）
       自己决定哪些是新的。
    2. **幂等**。水位线严格单调递增，重复调用不会重发，也不会漏发。
       因此「抓取后立即推送」与「定时兜底轮询」可以安全共存。
    3. **分类隔离**。finance / forum 各自一条水位线，互不干扰。
    4. **不丢批**。单轮最多取 batch_limit 条，水位线只推进到实际发送的
       最大 id，剩余条目在下一轮继续推送。

    Returns:
        {category: 本次广播条数}，仅包含有新增的分类。
    """
    if not _watermark_initialized:
        # 兜底：调用方忘记初始化时，避免把历史库当成新增全量广播
        init_broadcast_watermark()
        return {}

    pushed: Dict[str, int] = {}
    global _last_broadcast_ts
    cache_invalidated = False

    with _broadcast_lock:
        for category in BROADCAST_CATEGORIES:
            after_id = _broadcast_watermarks.get(category, 0)
            try:
                items = db_get_news_after_id(after_id, limit=batch_limit,
                                             category=category)
            except Exception as e:  # noqa: BLE001
                logger.error(f"拉取 {category} 增量新闻失败 (after_id={after_id}): {e}")
                continue

            if not items:
                continue

            # items 按 id 升序；水位线推进到本批最大 id
            new_watermark = items[-1].id or after_id
            _broadcast_watermarks[category] = max(after_id, new_watermark)

            # 拉取用 id 升序（水位线语义），推送需与列表页排序键一致
            # （db_query_news 用 ORDER BY publish_ts DESC, id DESC），
            # 否则前端 prepend 进去的这一段与列表其余部分顺序错乱。
            dicts = [n.to_dict() for n in items]
            dicts.sort(key=lambda d: (d.get("publish_ts") or 0, d.get("id") or 0),
                       reverse=True)
            total_new = len(dicts)
            truncated = total_new >= batch_limit
            payload_items = dicts[:SSE_MAX_ITEMS_PER_EVENT]

            if not cache_invalidated:
                invalidate_api_cache()
                cache_invalidated = True

            _sse_broadcast({
                "type": "new_news",
                "category": category,
                "items": payload_items,
                "count": total_new,
                # items 被截断时前端应整表刷新而非局部插入，否则会漏条目
                "truncated": truncated or total_new > len(payload_items),
                "ts": time.time(),
            })
            pushed[category] = total_new
            logger.info(
                f"SSE 增量广播 [{category}]: {total_new} 条 "
                f"(payload={len(payload_items)}, 水位 {after_id} -> "
                f"{_broadcast_watermarks[category]}, 客户端 {len(_sse_clients)})"
            )

    if pushed:
        # 仅在有真实增量时更新，使 /api/sse/health 的 last_broadcast_ts 能区分
        # 「存活但无新数据」与「桥接已死」。
        _last_broadcast_ts = time.time()
    return pushed


def update_web_state(news, stats, cycle, total, new_count, status, force_broadcast=False):
    """更新 Web 仪表盘共享状态（线程安全）。

    ⚠️ 本函数**只负责状态**（供 /api/stats 展示），不再承担「计算增量」的职责。
    增量推送统一由 broadcast_new_news() 基于数据库自增 id 完成。

    force_broadcast: 保留参数以兼容既有调用方；为 True 时触发一次
                     broadcast_new_news()（幂等，不会重复推送）。
    """
    news_dicts = [n.to_dict() if isinstance(n, NewsItem) else n for n in (news or [])[:500]]
    sources_list = list(dict.fromkeys(get_display_name(k) for k in stats.keys()))
    last_update = now_bj().strftime("%Y-%m-%d %H:%M:%S")

    with _web_state_lock:
        _web_state["news"] = news_dicts
        _web_state["stats"] = stats
        _web_state["cycle"] = cycle
        _web_state["total"] = total
        _web_state["new_count"] = new_count
        _web_state["status"] = status
        _web_state["sources"] = sources_list
        _web_state["last_update"] = last_update
        _web_state["server_ts"] = time.time()

    if force_broadcast:
        broadcast_new_news()
