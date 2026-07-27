#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite 数据库封装

特性：
- WAL 模式提升读写并发性能
- FTS5 全文检索（触发器自动同步）
- 线程独立连接
- 批量插入优化
- 简洁的核心表结构
"""

import sqlite3
import time
import logging
import threading
import json
from contextlib import contextmanager
from typing import Optional, Dict, List, Tuple, Any

from finfeed.config.settings import DB_PATH, USE_WAL_MODE
from finfeed.utils.time_utils import now_bj, bj_str_from_ts, ts_from_bj_str
from .models import NewsItem

logger = logging.getLogger("news_monitor")


class NewsDatabase:
    """新闻数据库管理器"""

    STAT_CACHE_TTL = 5

    def __init__(self) -> None:
        self._local = threading.local()
        self._stats_cache: Optional[Dict[str, Any]] = None
        self._stats_cache_ts: float = 0
        self._lock = threading.Lock()

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（线程安全，每个线程独立连接，自动重连）"""
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                try:
                    conn.close()
                except Exception:
                    pass
                self._local.conn = None

        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.text_factory = str
        if USE_WAL_MODE:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA mmap_size=268435456")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA encoding='UTF-8'")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")

        self._local.conn = conn
        return conn

    @contextmanager
    def get_db(self):
        """数据库上下文管理器（带事务支持）"""
        conn = self._get_conn()
        c = conn.cursor()
        try:
            yield c
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"数据库操作失败: {e}")
            raise

    def init_db(self) -> None:
        """初始化数据库表结构"""
        with self.get_db() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL DEFAULT '#',
                    source TEXT NOT NULL,
                    publish_time TEXT,
                    publish_ts INTEGER DEFAULT 0,
                    intro TEXT DEFAULT '',
                    created_at TEXT,
                    category TEXT DEFAULT '',
                    sentiment TEXT DEFAULT 'neutral',
                    importance REAL DEFAULT 0.0,
                    keywords TEXT DEFAULT '[]',
                    stocks TEXT DEFAULT '[]',
                    is_read INTEGER DEFAULT 0,
                    is_favorite INTEGER DEFAULT 0
                )
            """)

            self._create_indexes(c)
            self._setup_fts5(c)

            c.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS source_health (
                    source_name TEXT PRIMARY KEY,
                    total_requests INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    consecutive_failures INTEGER DEFAULT 0,
                    avg_latency REAL DEFAULT 0.0,
                    last_success_ts INTEGER DEFAULT 0,
                    last_failure_ts INTEGER DEFAULT 0,
                    last_error TEXT DEFAULT '',
                    is_circuit_open INTEGER DEFAULT 0,
                    circuit_open_ts INTEGER DEFAULT 0
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS source_last_ts (
                    source_name TEXT PRIMARY KEY,
                    last_ts INTEGER DEFAULT 0,
                    updated_at TEXT
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS stock_meta (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    industry TEXT DEFAULT '',
                    market TEXT DEFAULT '',
                    updated_at TEXT
                )
            """)

    def _create_indexes(self, c: sqlite3.Cursor) -> None:
        """创建精简后的核心索引"""
        c.execute("CREATE INDEX IF NOT EXISTS idx_pubts ON news(publish_ts DESC, id DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_source_ts ON news(source, publish_ts DESC, id DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_category_ts ON news(category, publish_ts DESC, id DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_fav_ts ON news(is_favorite, publish_ts DESC, id DESC)")
        
        c.execute("PRAGMA index_list('news')")
        existing_indexes = [row[1] for row in c.fetchall()]
        if 'idx_url_source' not in existing_indexes:
            try:
                c.execute("""
                    DELETE FROM news
                    WHERE rowid NOT IN (
                        SELECT MIN(rowid)
                        FROM news
                        GROUP BY url, source
                    )
                """)
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_url_source ON news(url, source)")
            except sqlite3.OperationalError:
                pass

    def _setup_fts5(self, c: sqlite3.Cursor) -> None:
        """设置FTS5全文检索及触发器自动同步"""
        try:
            c.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
                    title, intro, content='news', content_rowid='id',
                    tokenize='unicode61'
                )
            """)

            c.execute("""
                CREATE TRIGGER IF NOT EXISTS news_ai AFTER INSERT ON news BEGIN
                    INSERT INTO news_fts(rowid, title, intro) VALUES (new.id, new.title, new.intro);
                END
            """)
            c.execute("""
                CREATE TRIGGER IF NOT EXISTS news_ad AFTER DELETE ON news BEGIN
                    INSERT INTO news_fts(news_fts, rowid, title, intro) VALUES ('delete', old.id, old.title, old.intro);
                END
            """)
            c.execute("""
                CREATE TRIGGER IF NOT EXISTS news_au AFTER UPDATE ON news BEGIN
                    INSERT INTO news_fts(news_fts, rowid, title, intro) VALUES ('delete', old.id, old.title, old.intro);
                    INSERT INTO news_fts(rowid, title, intro) VALUES (new.id, new.title, new.intro);
                END
            """)
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS5设置失败: {e}")

    @staticmethod
    def _row_to_news(row: sqlite3.Row) -> NewsItem:
        """将数据库行转换为 NewsItem"""
        source = row["source"] if row["source"] is not None else ""
        publish_time = row["publish_time"] if row["publish_time"] is not None else ""
        publish_ts = row["publish_ts"] if row["publish_ts"] is not None else 0

        if source == "巨潮公告":
            created_at_val = row["created_at"] if "created_at" in row.keys() else ""
            if created_at_val:
                publish_time = created_at_val
                publish_ts = ts_from_bj_str(created_at_val)

        keywords_val = row["keywords"] if row["keywords"] is not None else "[]"
        stocks_val = row["stocks"] if row["stocks"] is not None else "[]"

        try:
            keywords: List[str] = json.loads(keywords_val) if keywords_val else []
        except (json.JSONDecodeError, TypeError):
            keywords = []
        try:
            stocks: List[str] = json.loads(stocks_val) if stocks_val else []
        except (json.JSONDecodeError, TypeError):
            stocks = []

        importance_val = row["importance"] if row["importance"] is not None else 0.0
        if importance_val < 2.0:
            try:
                from finfeed.analysis.importance import compute_importance
                title_val = row["title"] if row["title"] is not None else ""
                intro_val = row["intro"] if row["intro"] is not None else ""
                importance_val = compute_importance(
                    title=title_val,
                    intro=intro_val,
                    source=source,
                    stocks_count=len(stocks)
                )
            except Exception as e:
                logger.debug(f"重算重要性失败，使用默认值: {e}")
                importance_val = 5.0 if importance_val <= 0 else importance_val

        return NewsItem(
            id=row["id"] if "id" in row.keys() else None,
            title=row["title"] if row["title"] is not None else "",
            url=(row["url"] if row["url"] is not None else "#") or "#",
            source=source,
            publish_time=publish_time,
            publish_ts=publish_ts,
            intro=row["intro"] if row["intro"] is not None else "",
            created_at=row["created_at"] if "created_at" in row.keys() and row["created_at"] is not None else "",
            category=row["category"] if row["category"] is not None else "",
            sentiment=(row["sentiment"] if row["sentiment"] is not None else "neutral") or "neutral",
            importance=importance_val,
            keywords=keywords,
            stocks=stocks,
            is_read=bool(row["is_read"]) if "is_read" in row.keys() and row["is_read"] is not None else False,
            is_favorite=bool(row["is_favorite"]) if "is_favorite" in row.keys() and row["is_favorite"] is not None else False,
        )

    def insert_news(self, news_list: List[NewsItem]) -> Tuple[List[NewsItem], int]:
        """批量插入新闻（优化版：使用INSERT OR IGNORE + (url,source)唯一索引去重）

        Args:
            news_list: 新闻条目列表

        Returns:
            (新增新闻列表, 新增数量)
        """
        if not news_list:
            return [], 0

        inserted_items: List[NewsItem] = []
        now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")

        rows_to_insert: List[Tuple[Any, ...]] = []
        for n in news_list:
            title = n.title.strip()
            if not title:
                continue
            url = (n.url or "#").strip()
            source = n.source.strip()
            if not source:
                continue
            rows_to_insert.append((
                title,
                url,
                source,
                n.publish_time,
                n.publish_ts,
                n.intro or "",
                now_str,
                n.category or "",
                n.sentiment or "neutral",
                n.importance or 0.0,
                json.dumps(n.keywords, ensure_ascii=False),
                json.dumps(n.stocks, ensure_ascii=False),
                1 if n.is_read else 0,
                1 if n.is_favorite else 0,
                url,
                source,
            ))

        if not rows_to_insert:
            return [], 0

        with self.get_db() as c:
            c.executemany(
                """INSERT OR IGNORE INTO news
                   (title, url, source, publish_time, publish_ts, intro,
                    created_at, category, sentiment, importance, keywords, stocks, is_read, is_favorite)
                   SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                   WHERE NOT EXISTS (
                       SELECT 1 FROM news WHERE url = ? AND source = ? AND title = ?
                   )
                """,
                [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], r[12], r[13],
                  r[14], r[15], r[0]) for r in rows_to_insert]
            )

            c.execute(
                "SELECT id, title, url, source FROM news WHERE created_at = ? AND id IN (SELECT last_insert_rowid())",
                (now_str,)
            )
            recent_rows = {row["title"]: row for row in c.fetchall()}

            for n in news_list:
                if n.title in recent_rows:
                    row = recent_rows[n.title]
                    n.id = row["id"]
                    n.created_at = now_str
                    inserted_items.append(n)

        if inserted_items:
            self.invalidate_stats_cache()
        return inserted_items, len(inserted_items)

    def get_recent_news(self, limit: int = 200, source: Optional[str] = None,
                        category: Optional[str] = None) -> List[NewsItem]:
        """从数据库获取最近的新闻"""
        with self.get_db() as c:
            if source and source != "all":
                c.execute(
                    "SELECT * FROM news WHERE source = ? ORDER BY publish_ts DESC, id DESC LIMIT ?",
                    (source, limit),
                )
            elif category:
                c.execute(
                    "SELECT * FROM news WHERE category = ? ORDER BY publish_ts DESC, id DESC LIMIT ?",
                    (category, limit),
                )
            else:
                c.execute(
                    "SELECT * FROM news ORDER BY publish_ts DESC, id DESC LIMIT ?",
                    (limit,),
                )
            return [self._row_to_news(row) for row in c.fetchall()]

    def get_news_by_id(self, news_id: int) -> Optional[NewsItem]:
        """根据 ID 获取单条新闻详情"""
        if not news_id:
            return None
        with self.get_db() as c:
            c.execute("SELECT * FROM news WHERE id = ? LIMIT 1", (news_id,))
            row = c.fetchone()
            if row:
                return self._row_to_news(row)
            return None

    def get_all_for_export(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                           category: Optional[str] = None) -> List[NewsItem]:
        """获取所有新闻用于导出"""
        with self.get_db() as c:
            query = "SELECT * FROM news WHERE 1=1"
            params: List[Any] = []
            if start_date:
                query += " AND publish_time >= ?"
                params.append(start_date)
            if end_date:
                query += " AND publish_time <= ?"
                params.append(end_date + " 23:59:59")
            if category:
                query += " AND category = ?"
                params.append(category)
            query += " ORDER BY publish_ts DESC, id DESC"
            c.execute(query, params)
            return [self._row_to_news(row) for row in c.fetchall()]

    def get_date_range(self) -> Tuple[str, str, List[str]]:
        """获取数据库中新闻的时间范围及所有有数据的日期"""
        with self.get_db() as c:
            try:
                c.execute("SELECT MIN(publish_time) as min_date, MAX(publish_time) as max_date FROM news")
                row = c.fetchone()
                c.execute("SELECT DISTINCT substr(publish_time, 1, 10) as d FROM news WHERE publish_time IS NOT NULL AND publish_time != '' ORDER BY d")
                dates = [r["d"] for r in c.fetchall()]
                if row and row["min_date"] and row["max_date"]:
                    return row["min_date"][:10], row["max_date"][:10], dates
            except Exception as e:
                logger.debug(f"获取日期范围失败: {e}")
            return "", "", []

    def search_news(self, keyword: str, limit: int = 100) -> List[NewsItem]:
        """全文搜索新闻"""
        if not keyword:
            return []
        with self.get_db() as c:
            try:
                escaped = keyword.replace('"', '""')
                c.execute(
                    """SELECT n.* FROM news n
                       INNER JOIN news_fts f ON n.id = f.rowid
                       WHERE news_fts MATCH ?
                       ORDER BY n.publish_ts DESC, n.id DESC LIMIT ?""",
                    (f'"{escaped}"', limit),
                )
                return [self._row_to_news(row) for row in c.fetchall()]
            except Exception as e:
                logger.debug(f"FTS5 搜索失败，回退到 LIKE 查询: {e}")
                c.execute(
                    """SELECT * FROM news
                       WHERE title LIKE ? OR intro LIKE ?
                       ORDER BY publish_ts DESC, id DESC LIMIT ?""",
                    (f"%{keyword}%", f"%{keyword}%", limit),
                )
                return [self._row_to_news(row) for row in c.fetchall()]

    def get_last_exit_ts(self) -> int:
        """读取上次程序退出时保存的时间戳"""
        try:
            with self.get_db() as c:
                c.execute("SELECT value FROM metadata WHERE key = 'last_exit_ts'")
                row = c.fetchone()
                if row:
                    return int(row["value"])
        except Exception as e:
            logger.debug(f"读取 last_exit_ts 失败: {e}")
        return 0

    def set_last_exit_ts(self, ts: int) -> None:
        """保存当前程序的最新活跃时间戳"""
        try:
            with self.get_db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_exit_ts', ?)",
                    (str(ts),),
                )
        except Exception as e:
            logger.warning(f"保存 last_exit_ts 失败: {e}")

    def get_source_last_ts(self, source_name: str) -> int:
        """获取指定源的增量时间戳"""
        try:
            with self.get_db() as c:
                c.execute("SELECT last_ts FROM source_last_ts WHERE source_name = ?", (source_name,))
                row = c.fetchone()
                if row:
                    return int(row["last_ts"])
        except Exception as e:
            logger.debug(f"读取源 {source_name} 时间戳失败: {e}")
        return 0

    def set_source_last_ts(self, source_name: str, ts: int) -> None:
        """保存指定源的增量时间戳"""
        try:
            with self.get_db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO source_last_ts (source_name, last_ts, updated_at) VALUES (?, ?, ?)",
                    (source_name, ts, now_bj().strftime("%Y-%m-%d %H:%M:%S")),
                )
        except Exception as e:
            logger.warning(f"保存源 {source_name} 时间戳失败: {e}")

    def get_all_source_last_ts(self) -> Dict[str, int]:
        """获取所有源的增量时间戳"""
        result: Dict[str, int] = {}
        try:
            with self.get_db() as c:
                c.execute("SELECT source_name, last_ts FROM source_last_ts")
                for row in c.fetchall():
                    result[row["source_name"]] = int(row["last_ts"])
        except Exception as e:
            logger.debug(f"读取所有源时间戳失败: {e}")
        return result

    def get_metadata(self, key: str, default: str = "") -> str:
        """获取元数据"""
        try:
            with self.get_db() as c:
                c.execute("SELECT value FROM metadata WHERE key = ?", (key,))
                row = c.fetchone()
                return row["value"] if row else default
        except Exception as e:
            logger.debug(f"读取元数据 {key} 失败: {e}")
            return default

    def set_metadata(self, key: str, value: str) -> None:
        """设置元数据"""
        try:
            with self.get_db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    (key, value),
                )
        except Exception as e:
            logger.warning(f"保存元数据 {key} 失败: {e}")

    # -------------------- 股票元数据 --------------------
    _STOCK_NAME_CACHE: Dict[str, str] = {}
    _STOCK_CACHE_LOADED = False

    def load_stock_meta_batch(self, stock_map: Dict[str, str]) -> int:
        """批量写入股票元数据（不存在的才插入，已存在的不覆盖）"""
        if not stock_map:
            return 0
        now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self.get_db() as c:
                rows = [(code, name, now_str) for code, name in stock_map.items()]
                c.executemany(
                    "INSERT OR IGNORE INTO stock_meta (code, name, updated_at) VALUES (?, ?, ?)",
                    rows,
                )
                return c.rowcount if c.rowcount > 0 else len(rows)
        except Exception as e:
            logger.warning(f"批量写入股票元数据失败: {e}")
            return 0

    def get_stock_name(self, code: str) -> str:
        """获取股票名称（带内存缓存）"""
        if not code:
            return ""
        if NewsDatabase._STOCK_NAME_CACHE and code in NewsDatabase._STOCK_NAME_CACHE:
            return NewsDatabase._STOCK_NAME_CACHE[code]
        try:
            with self.get_db() as c:
                c.execute("SELECT name FROM stock_meta WHERE code = ?", (code,))
                row = c.fetchone()
                if row:
                    NewsDatabase._STOCK_NAME_CACHE[code] = row["name"]
                    return row["name"]
        except Exception as e:
            logger.debug(f"查询股票 {code} 名称失败: {e}")
        return ""

    def get_all_stock_names(self) -> Dict[str, str]:
        """获取所有股票代码→名称映射"""
        result: Dict[str, str] = {}
        try:
            with self.get_db() as c:
                c.execute("SELECT code, name FROM stock_meta")
                for row in c.fetchall():
                    result[row["code"]] = row["name"]
                NewsDatabase._STOCK_NAME_CACHE = dict(result)
                NewsDatabase._STOCK_CACHE_LOADED = True
        except Exception as e:
            logger.debug(f"查询所有股票名称失败: {e}")
        return result

    def mark_read(self, news_id: int, is_read: bool = True) -> None:
        """标记新闻已读/未读"""
        with self.get_db() as c:
            c.execute(
                "UPDATE news SET is_read = ? WHERE id = ?",
                (1 if is_read else 0, news_id),
            )
        self.invalidate_stats_cache()

    def toggle_favorite(self, news_id: int) -> bool:
        """切换收藏状态，返回新状态"""
        with self.get_db() as c:
            c.execute("SELECT is_favorite FROM news WHERE id = ?", (news_id,))
            row = c.fetchone()
            if not row:
                return False
            new_state = 0 if row["is_favorite"] else 1
            c.execute(
                "UPDATE news SET is_favorite = ? WHERE id = ?",
                (new_state, news_id),
            )
            self.invalidate_stats_cache()
            return bool(new_state)

    def get_favorites(self, limit: int = 100) -> List[NewsItem]:
        """获取收藏的新闻"""
        with self.get_db() as c:
            c.execute(
                "SELECT * FROM news WHERE is_favorite = 1 ORDER BY publish_ts DESC, id DESC LIMIT ?",
                (limit,),
            )
            return [self._row_to_news(row) for row in c.fetchall()]

    _QUERY_NEWS_COLUMNS = "id, title, url, source, publish_time, publish_ts, intro, created_at, category, sentiment, importance, keywords, stocks, is_read, is_favorite"

    def query_news(
        self,
        limit: int = 50,
        offset: int = 0,
        source: Optional[str] = None,
        keyword: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        sentiment: Optional[str] = None,
        is_favorite: Optional[bool] = None,
        stock_name: Optional[str] = None,
        min_importance: Optional[float] = None,
        count_only: bool = False,
        source_include_list: Optional[List[str]] = None,
        source_exclude_list: Optional[List[str]] = None,
        category: Optional[str] = None,
    ) -> Tuple[List[NewsItem], int]:
        """通用新闻查询方法，支持分页、筛选

        Returns:
            (新闻列表, 总数)
        """
        conditions: List[str] = []
        params: List[Any] = []

        if source and source != "all":
            conditions.append("source = ?")
            params.append(source)
        if source_include_list:
            placeholders = ",".join("?" * len(source_include_list))
            conditions.append(f"source IN ({placeholders})")
            params.extend(source_include_list)
        if source_exclude_list:
            placeholders = ",".join("?" * len(source_exclude_list))
            conditions.append(f"source NOT IN ({placeholders})")
            params.extend(source_exclude_list)
        if category:
            conditions.append("category = ?")
            params.append(category)
        if start_ts is not None:
            conditions.append("publish_ts >= ?")
            params.append(start_ts)
        if end_ts is not None:
            conditions.append("publish_ts <= ?")
            params.append(end_ts)
        if sentiment and sentiment != "all":
            conditions.append("sentiment = ?")
            params.append(sentiment)
        if is_favorite is not None:
            conditions.append("is_favorite = ?")
            params.append(1 if is_favorite else 0)
        if min_importance is not None and min_importance > 0:
            conditions.append("importance >= ?")
            params.append(min_importance)
        if stock_name:
            conditions.append("stocks LIKE ?")
            params.append(f"%{stock_name}%")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self.get_db() as c:
            c.execute(f"SELECT COUNT(*) as cnt FROM news WHERE {where_clause}", params)
            total = c.fetchone()["cnt"]

            if count_only:
                return [], total

            if keyword:
                try:
                    escaped = keyword.replace('"', '""')
                    fts_query = f'"{escaped}"'
                    data_query = f"""
                        SELECT n.{self._QUERY_NEWS_COLUMNS} FROM news n
                        INNER JOIN news_fts f ON n.id = f.rowid
                        WHERE news_fts MATCH ? AND ({where_clause.replace('source', 'n.source').replace('publish_ts', 'n.publish_ts').replace('sentiment', 'n.sentiment').replace('is_favorite', 'n.is_favorite').replace('importance', 'n.importance').replace('stocks', 'n.stocks').replace('category', 'n.category')})
                        ORDER BY n.publish_ts DESC, n.id DESC
                        LIMIT ? OFFSET ?
                    """
                    c.execute(data_query, [fts_query] + params + [limit, offset])
                    items = [self._row_to_news(row) for row in c.fetchall()]
                    return items, total
                except Exception as e:
                    logger.debug(f"FTS5 复合查询失败，回退到 LIKE: {e}")

            like_clause = f"({where_clause})"
            like_params = list(params)
            if keyword:
                like_clause += " AND (title LIKE ? OR intro LIKE ?)"
                like_params.extend([f"%{keyword}%", f"%{keyword}%"])

            data_query = f"""
                SELECT {self._QUERY_NEWS_COLUMNS} FROM news
                WHERE {like_clause}
                ORDER BY publish_ts DESC, id DESC
                LIMIT ? OFFSET ?
            """
            c.execute(data_query, like_params + [limit, offset])
            items = [self._row_to_news(row) for row in c.fetchall()]
            return items, total

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息（带短TTL缓存）"""
        now = time.time()
        if self._stats_cache is not None and (now - self._stats_cache_ts) < self.STAT_CACHE_TTL:
            return dict(self._stats_cache)

        with self.get_db() as c:
            now_ts = int(now)
            day_ago = now_ts - 86400
            week_ago = now_ts - 7 * 86400

            c.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN publish_ts >= ? THEN 1 ELSE 0 END) as total_24h,
                    SUM(CASE WHEN is_favorite = 1 THEN 1 ELSE 0 END) as fav_count,
                    SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) as unread_count,
                    COUNT(DISTINCT source) as source_count
                FROM news
            """, (day_ago,))
            row = c.fetchone()
            total = row["total"] or 0
            total_24h = row["total_24h"] or 0
            fav_count = row["fav_count"] or 0
            unread_count = row["unread_count"] or 0
            source_count = row["source_count"] or 0

            c.execute(
                "SELECT sentiment, COUNT(*) as cnt FROM news GROUP BY sentiment"
            )
            sentiment_stats = {"positive": 0, "negative": 0, "neutral": 0}
            for r in c.fetchall():
                s = r["sentiment"] or "neutral"
                sentiment_stats[s] = r["cnt"]

            c.execute(
                "SELECT source, COUNT(*) as cnt FROM news WHERE publish_ts >= ? GROUP BY source ORDER BY cnt DESC",
                (week_ago,),
            )
            source_stats = {r["source"]: r["cnt"] for r in c.fetchall()}

            c.execute(
                """SELECT strftime('%m-%d %H:00', publish_ts, 'unixepoch', 'localtime') as hour_bucket,
                       COUNT(*) as cnt
                   FROM news WHERE publish_ts >= ?
                   GROUP BY hour_bucket ORDER BY hour_bucket""",
                (day_ago,),
            )
            time_trend = [{"time": r["hour_bucket"] or "", "count": r["cnt"]} for r in c.fetchall()]

            c.execute(
                "SELECT category, COUNT(*) as cnt FROM news WHERE category != '' GROUP BY category ORDER BY cnt DESC"
            )
            category_stats = {r["category"]: r["cnt"] for r in c.fetchall()}

            importance_dist = {"极重要": 0, "重要": 0, "一般": 0, "较低": 0, "低": 0}
            c.execute(
                """SELECT
                    CASE
                        WHEN importance >= 8.0 THEN '极重要'
                        WHEN importance >= 6.5 THEN '重要'
                        WHEN importance >= 5.0 THEN '一般'
                        WHEN importance >= 3.0 THEN '较低'
                        ELSE '低'
                    END as level, COUNT(*) as cnt
                   FROM news GROUP BY level"""
            )
            for r in c.fetchall():
                importance_dist[r["level"]] = r["cnt"]

            result = {
                "total_news": total,
                "total_24h": total_24h,
                "favorite_count": fav_count,
                "unread_count": unread_count,
                "source_count": source_count,
                "sentiment_stats": sentiment_stats,
                "source_stats": source_stats,
                "time_trend": time_trend,
                "category_stats": category_stats,
                "importance_distribution": importance_dist,
                "update_time": now_bj().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._stats_cache = dict(result)
            self._stats_cache_ts = now
            return result

    def invalidate_stats_cache(self) -> None:
        """强制失效统计缓存（在插入新数据后调用）"""
        self._stats_cache = None
        self._stats_cache_ts = 0

    def count_news(self) -> int:
        """统计新闻总数"""
        with self.get_db() as c:
            c.execute("SELECT COUNT(*) as cnt FROM news")
            row = c.fetchone()
            return row["cnt"] if row else 0

    def close(self) -> None:
        """关闭数据库连接"""
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None


_global_db: Optional[NewsDatabase] = None
_db_lock = threading.Lock()


def get_db_manager() -> NewsDatabase:
    """获取全局数据库管理器单例（线程安全）"""
    global _global_db
    if _global_db is None:
        with _db_lock:
            if _global_db is None:
                _global_db = NewsDatabase()
    return _global_db


def init_db() -> None:
    """初始化数据库表结构"""
    get_db_manager().init_db()


def db_load_stock_meta_batch(stock_map: Dict[str, str]) -> int:
    """批量写入股票元数据"""
    return get_db_manager().load_stock_meta_batch(stock_map)


def db_get_stock_name(code: str) -> str:
    """获取股票名称"""
    return get_db_manager().get_stock_name(code)


def db_get_all_stock_names() -> Dict[str, str]:
    """获取所有股票代码→名称映射"""
    return get_db_manager().get_all_stock_names()


def db_update_stock_meta(stock_map: Dict[str, str]) -> int:
    """批量更新股票元数据（不存在的才插入，已存在的不覆盖）"""
    return get_db_manager().load_stock_meta_batch(stock_map)


def db_insert_news(news_list: List[NewsItem]) -> Tuple[List[NewsItem], int]:
    """插入新闻到数据库"""
    return get_db_manager().insert_news(news_list)


def db_get_recent_news(limit: int = 200, source: Optional[str] = None,
                       category: Optional[str] = None) -> List[NewsItem]:
    """从数据库获取最近的新闻"""
    return get_db_manager().get_recent_news(limit, source, category)


def db_get_news_by_id(news_id: int) -> Optional[NewsItem]:
    """根据 ID 获取单条新闻详情"""
    return get_db_manager().get_news_by_id(news_id)


def db_get_all_for_export(start_date: Optional[str] = None, end_date: Optional[str] = None,
                          category: Optional[str] = None) -> List[NewsItem]:
    """获取所有新闻用于导出"""
    return get_db_manager().get_all_for_export(start_date, end_date, category)


def db_get_date_range() -> Tuple[str, str, List[str]]:
    """获取数据库中新闻的时间范围"""
    return get_db_manager().get_date_range()


def db_search_news(keyword: str, limit: int = 100) -> List[NewsItem]:
    """全文搜索新闻"""
    return get_db_manager().search_news(keyword, limit)


def db_get_last_exit_ts() -> int:
    """读取上次程序退出时保存的时间戳"""
    return get_db_manager().get_last_exit_ts()


def db_set_last_exit_ts(ts: int) -> None:
    """保存当前程序的最新活跃时间戳"""
    get_db_manager().set_last_exit_ts(ts)


def db_get_source_last_ts(source_name: str) -> int:
    """获取指定源的增量时间戳"""
    return get_db_manager().get_source_last_ts(source_name)


def db_set_source_last_ts(source_name: str, ts: int) -> None:
    """保存指定源的增量时间戳"""
    get_db_manager().set_source_last_ts(source_name, ts)


def db_get_all_source_last_ts() -> Dict[str, int]:
    """获取所有源的增量时间戳"""
    return get_db_manager().get_all_source_last_ts()


def db_get_metadata(key: str, default: str = "") -> str:
    """获取元数据"""
    return get_db_manager().get_metadata(key, default)


def db_set_metadata(key: str, value: str) -> None:
    """设置元数据"""
    get_db_manager().set_metadata(key, value)


def db_mark_read(news_id: int, is_read: bool = True) -> None:
    """标记新闻已读/未读"""
    get_db_manager().mark_read(news_id, is_read)


def db_toggle_favorite(news_id: int) -> bool:
    """切换收藏状态，返回新状态"""
    return get_db_manager().toggle_favorite(news_id)


def db_get_favorites(limit: int = 100) -> List[NewsItem]:
    """获取收藏的新闻"""
    return get_db_manager().get_favorites(limit)


def db_count_news() -> int:
    """统计新闻总数"""
    return get_db_manager().count_news()


def db_query_news(
    limit: int = 50,
    offset: int = 0,
    source: Optional[str] = None,
    keyword: Optional[str] = None,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
    sentiment: Optional[str] = None,
    is_favorite: Optional[bool] = None,
    stock_name: Optional[str] = None,
    min_importance: Optional[float] = None,
    source_include_list: Optional[List[str]] = None,
    source_exclude_list: Optional[List[str]] = None,
    category: Optional[str] = None,
) -> Tuple[List[NewsItem], int]:
    """通用新闻查询"""
    return get_db_manager().query_news(
        limit=limit, offset=offset, source=source, keyword=keyword,
        start_ts=start_ts, end_ts=end_ts, sentiment=sentiment,
        is_favorite=is_favorite, stock_name=stock_name, min_importance=min_importance,
        source_include_list=source_include_list, source_exclude_list=source_exclude_list,
        category=category,
    )


def db_get_statistics() -> Dict[str, Any]:
    """获取增强统计信息"""
    return get_db_manager().get_statistics()


def db_invalidate_stats_cache() -> None:
    """强制失效统计缓存"""
    get_db_manager().invalidate_stats_cache()


def db_close() -> None:
    """关闭数据库连接"""
    get_db_manager().close()


@contextmanager
def get_db():
    """模块级数据库上下文管理器（兼容旧代码）"""
    with get_db_manager().get_db() as c:
        yield c
