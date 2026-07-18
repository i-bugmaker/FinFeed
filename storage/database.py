#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite 数据库封装

增强特性：
- WAL 模式提升读写并发性能
- FTS5 全文检索
- 增量哈希加载（只加载最近 N 天，降低启动开销）
- 元数据表存储运行状态
- 自选股、订阅、标签等新表
"""

import sqlite3
import time
import logging
import threading
import json
from contextlib import contextmanager
from typing import Optional, Dict, List, Tuple, Any

from config.settings import (
    DB_PATH, USE_WAL_MODE, DEDUP_RECENT_DAYS,
)
from utils.time_utils import now_bj, bj_str_from_ts
from utils.hash_utils import compute_title_full_hash, compute_url_hash, simhash_to_hex, hex_to_simhash
from storage.models import NewsItem

logger = logging.getLogger("news_monitor")


class NewsDatabase:
    """新闻数据库管理器"""

    def __init__(self):
        self._local = threading.local()
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接（线程安全）"""
        if hasattr(self._local, 'conn') and self._local.conn is not None:
            return self._local.conn

        if self._conn is not None:
            return self._conn

        self._conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.text_factory = str
        if USE_WAL_MODE:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA cache_size=-20000")
        self._conn.execute("PRAGMA encoding='UTF-8'")

        return self._conn

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

    @contextmanager
    def get_conn_ctx(self):
        """数据库连接上下文管理器"""
        conn = self._get_conn()
        try:
            yield conn
        except Exception as e:
            conn.rollback()
            logger.error(f"数据库连接操作失败: {e}")
            raise

    def _migrate_news_columns(self, c):
        """迁移 news 表，补齐缺失的列"""
        c.execute("PRAGMA table_info(news)")
        existing = {row[1] for row in c.fetchall()}
        expected = {
            "simhash": "TEXT DEFAULT ''",
            "category": "TEXT DEFAULT ''",
            "sentiment": "TEXT DEFAULT 'neutral'",
            "importance": "REAL DEFAULT 0.0",
            "keywords": "TEXT DEFAULT '[]'",
            "stocks": "TEXT DEFAULT '[]'",
            "is_read": "INTEGER DEFAULT 0",
            "is_favorite": "INTEGER DEFAULT 0",
            "tags": "TEXT DEFAULT '[]'",
        }
        for col, definition in expected.items():
            if col not in existing:
                try:
                    c.execute(f"ALTER TABLE news ADD COLUMN {col} {definition}")
                except sqlite3.OperationalError:
                    pass

    def init_db(self):
        """初始化数据库表结构"""
        with self.get_db() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS news (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT,
                    source TEXT NOT NULL,
                    publish_time TEXT,
                    publish_ts INTEGER DEFAULT 0,
                    intro TEXT,
                    title_hash TEXT,
                    created_at TEXT,
                    title_full_hash TEXT,
                    url_hash TEXT,
                    simhash TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    sentiment TEXT DEFAULT 'neutral',
                    importance REAL DEFAULT 0.0,
                    keywords TEXT DEFAULT '[]',
                    stocks TEXT DEFAULT '[]',
                    is_read INTEGER DEFAULT 0,
                    is_favorite INTEGER DEFAULT 0,
                    tags TEXT DEFAULT '[]'
                )
            """)

            self._migrate_news_columns(c)

            c.execute("CREATE INDEX IF NOT EXISTS idx_publish_ts ON news(publish_ts DESC, id DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_created ON news(created_at ASC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_title_full_hash ON news(title_full_hash)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_url_hash ON news(url_hash)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_source ON news(source)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_importance ON news(importance DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_favorite ON news(is_favorite) WHERE is_favorite=1")

            try:
                c.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
                        title, intro, content='news', content_rowid='id',
                        tokenize='unicode61'
                    )
                """)
            except sqlite3.OperationalError:
                pass

            c.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    added_at TEXT,
                    UNIQUE(stock_code)
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    keywords TEXT DEFAULT '[]',
                    description TEXT DEFAULT '',
                    is_enabled INTEGER DEFAULT 1,
                    created_at TEXT
                )
            """)

            c.execute("""
                CREATE TABLE IF NOT EXISTS alert_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    rule_type TEXT NOT NULL,
                    rule_config TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    channel_config TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT
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

    @staticmethod
    def _row_to_news(row: sqlite3.Row) -> NewsItem:
        """将数据库行转换为 NewsItem"""

        def _safe_get(row_obj, key, default):
            try:
                val = row_obj[key]
                return val if val is not None else default
            except (KeyError, IndexError):
                return default

        return NewsItem(
            id=_safe_get(row, "id", None),
            title=_safe_get(row, "title", ""),
            url=_safe_get(row, "url", "#") or "#",
            source=_safe_get(row, "source", ""),
            publish_time=_safe_get(row, "publish_time", ""),
            publish_ts=_safe_get(row, "publish_ts", 0) or 0,
            intro=_safe_get(row, "intro", ""),
            title_full_hash=_safe_get(row, "title_full_hash", ""),
            url_hash=_safe_get(row, "url_hash", ""),
            simhash=hex_to_simhash(_safe_get(row, "simhash", "")) if _safe_get(row, "simhash", "") else 0,
            created_at=_safe_get(row, "created_at", ""),
            category=_safe_get(row, "category", ""),
            sentiment=_safe_get(row, "sentiment", "neutral") or "neutral",
            importance=_safe_get(row, "importance", 0.0) or 0.0,
            keywords=json.loads(_safe_get(row, "keywords", "[]") or "[]") if _safe_get(row, "keywords", "") else [],
            stocks=json.loads(_safe_get(row, "stocks", "[]") or "[]") if _safe_get(row, "stocks", "") else [],
            is_read=bool(_safe_get(row, "is_read", 0)) if _safe_get(row, "is_read", None) is not None else False,
            is_favorite=bool(_safe_get(row, "is_favorite", 0)) if _safe_get(row, "is_favorite", None) is not None else False,
            tags=json.loads(_safe_get(row, "tags", "[]") or "[]") if _safe_get(row, "tags", "") else [],
        )

    def insert_news(self, news_list: List[NewsItem]) -> Tuple[List[NewsItem], int]:
        """插入新闻到数据库（批量去重优化）

        Args:
            news_list: 新闻条目列表

        Returns:
            (新增新闻列表, 新增数量)
        """
        if not news_list:
            return [], 0

        with self.get_db() as c:
            recent_days_ts = int(time.time()) - DEDUP_RECENT_DAYS * 86400
            existing_title_hashes = set()
            existing_url_hashes = set()

            try:
                for row in c.execute(
                    "SELECT title_full_hash FROM news WHERE publish_ts >= ? AND title_full_hash IS NOT NULL",
                    (recent_days_ts,)
                ):
                    if row[0]:
                        existing_title_hashes.add(row[0])
                for row in c.execute(
                    "SELECT url_hash FROM news WHERE publish_ts >= ? AND url_hash IS NOT NULL AND url_hash != ''",
                    (recent_days_ts,)
                ):
                    if row[0]:
                        existing_url_hashes.add(row[0])
            except Exception:
                pass

            inserted_items = []
            inserted = 0
            now_str = now_bj().strftime("%Y-%m-%d %H:%M:%S")

            for n in news_list:
                title = n.title
                url = n.url or "#"

                title_full_hash = n.title_full_hash or compute_title_full_hash(title)
                if title_full_hash in existing_title_hashes:
                    continue

                url_hash = n.url_hash or compute_url_hash(url)
                if url_hash and url_hash in existing_url_hashes:
                    continue

                title_hash = f"{title[:30]}|{n.source}"
                simhash_hex = simhash_to_hex(n.simhash) if n.simhash else ""

                try:
                    c.execute(
                        """INSERT OR IGNORE INTO news
                           (title, url, source, publish_time, publish_ts, intro,
                            title_hash, created_at, title_full_hash, url_hash, simhash,
                            category, sentiment, importance, keywords, stocks, is_read, is_favorite, tags)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            title, url, n.source, n.publish_time, n.publish_ts, n.intro,
                            title_hash, now_str, title_full_hash, url_hash, simhash_hex,
                            n.category, n.sentiment, n.importance,
                            json.dumps(n.keywords, ensure_ascii=False),
                            json.dumps(n.stocks, ensure_ascii=False),
                            1 if n.is_read else 0,
                            1 if n.is_favorite else 0,
                            json.dumps(n.tags, ensure_ascii=False),
                        ),
                    )
                    if c.rowcount > 0:
                        new_id = c.lastrowid
                        n.id = new_id
                        n.created_at = now_str
                        inserted_items.append(n)
                        inserted += 1
                        existing_title_hashes.add(title_full_hash)
                        if url_hash:
                            existing_url_hashes.add(url_hash)
                        try:
                            c.execute(
                                "INSERT INTO news_fts(rowid, title, intro) VALUES (?, ?, ?)",
                                (new_id, title, n.intro or "")
                            )
                        except Exception:
                            pass
                except sqlite3.IntegrityError:
                    pass

        return inserted_items, inserted

    def get_recent_news(self, limit: int = 200, source: Optional[str] = None) -> List[NewsItem]:
        """从数据库获取最近的新闻"""
        with self.get_db() as c:
            if source and source != "all":
                c.execute(
                    "SELECT * FROM news WHERE source = ? ORDER BY publish_ts DESC, id DESC LIMIT ?",
                    (source, limit),
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

    def get_all_for_export(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[NewsItem]:
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
            except Exception:
                pass
            return "", "", []

    def search_news(self, keyword: str, limit: int = 100) -> List[NewsItem]:
        """全文搜索新闻"""
        with self.get_db() as c:
            try:
                c.execute(
                    """SELECT n.* FROM news n
                       INNER JOIN news_fts f ON n.id = f.rowid
                       WHERE news_fts MATCH ?
                       ORDER BY n.publish_ts DESC, n.id DESC LIMIT ?""",
                    (keyword, limit),
                )
                return [self._row_to_news(row) for row in c.fetchall()]
            except Exception:
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
        except Exception:
            pass
        return 0

    def set_last_exit_ts(self, ts: int):
        """保存当前程序的最新活跃时间戳"""
        try:
            with self.get_db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES ('last_exit_ts', ?)",
                    (str(ts),),
                )
        except Exception:
            pass

    def get_source_last_ts(self, source_name: str) -> int:
        """获取指定源的增量时间戳"""
        try:
            with self.get_db() as c:
                c.execute("SELECT last_ts FROM source_last_ts WHERE source_name = ?", (source_name,))
                row = c.fetchone()
                if row:
                    return int(row["last_ts"])
        except Exception:
            pass
        return 0

    def set_source_last_ts(self, source_name: str, ts: int):
        """保存指定源的增量时间戳"""
        try:
            with self.get_db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO source_last_ts (source_name, last_ts, updated_at) VALUES (?, ?, ?)",
                    (source_name, ts, now_bj().strftime("%Y-%m-%d %H:%M:%S")),
                )
        except Exception:
            pass

    def get_all_source_last_ts(self) -> Dict[str, int]:
        """获取所有源的增量时间戳"""
        result: Dict[str, int] = {}
        try:
            with self.get_db() as c:
                c.execute("SELECT source_name, last_ts FROM source_last_ts")
                for row in c.fetchall():
                    result[row["source_name"]] = int(row["last_ts"])
        except Exception:
            pass
        return result

    def get_metadata(self, key: str, default: str = "") -> str:
        """获取元数据"""
        try:
            with self.get_db() as c:
                c.execute("SELECT value FROM metadata WHERE key = ?", (key,))
                row = c.fetchone()
                return row["value"] if row else default
        except Exception:
            return default

    def set_metadata(self, key: str, value: str):
        """设置元数据"""
        try:
            with self.get_db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    (key, value),
                )
        except Exception:
            pass

    def mark_read(self, news_id: int, is_read: bool = True):
        """标记新闻已读/未读"""
        with self.get_db() as c:
            c.execute(
                "UPDATE news SET is_read = ? WHERE id = ?",
                (1 if is_read else 0, news_id),
            )

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
            return bool(new_state)

    def get_favorites(self, limit: int = 100) -> List[NewsItem]:
        """获取收藏的新闻"""
        with self.get_db() as c:
            c.execute(
                "SELECT * FROM news WHERE is_favorite = 1 ORDER BY publish_ts DESC, id DESC LIMIT ?",
                (limit,),
            )
            return [self._row_to_news(row) for row in c.fetchall()]

    def count_news(self) -> int:
        """统计新闻总数"""
        with self.get_db() as c:
            c.execute("SELECT COUNT(*) as cnt FROM news")
            row = c.fetchone()
            return row["cnt"] if row else 0

    def close(self):
        """关闭数据库连接"""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


_global_db: Optional[NewsDatabase] = None


def get_db_manager() -> NewsDatabase:
    """获取全局数据库管理器单例"""
    global _global_db
    if _global_db is None:
        _global_db = NewsDatabase()
    return _global_db


def get_conn() -> sqlite3.Connection:
    """获取数据库连接（单例）"""
    return get_db_manager()._get_conn()


@contextmanager
def get_db():
    """数据库上下文管理器"""
    with get_db_manager().get_conn_ctx() as conn:
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise


def init_db():
    """初始化数据库表结构"""
    get_db_manager().init_db()


def db_insert_news(news_list: List[NewsItem]) -> Tuple[List[NewsItem], int]:
    """插入新闻到数据库"""
    return get_db_manager().insert_news(news_list)


def db_get_recent_news(limit: int = 200, source: Optional[str] = None) -> List[NewsItem]:
    """从数据库获取最近的新闻"""
    return get_db_manager().get_recent_news(limit, source)


def db_get_news_by_id(news_id: int) -> Optional[NewsItem]:
    """根据 ID 获取单条新闻详情"""
    return get_db_manager().get_news_by_id(news_id)


def db_get_all_for_export(start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[NewsItem]:
    """获取所有新闻用于导出"""
    return get_db_manager().get_all_for_export(start_date, end_date)


def db_get_date_range() -> Tuple[str, str, List[str]]:
    """获取数据库中新闻的时间范围"""
    return get_db_manager().get_date_range()


def db_search_news(keyword: str, limit: int = 100) -> List[NewsItem]:
    """全文搜索新闻"""
    return get_db_manager().search_news(keyword, limit)


def db_get_last_exit_ts() -> int:
    """读取上次程序退出时保存的时间戳"""
    return get_db_manager().get_last_exit_ts()


def db_set_last_exit_ts(ts: int):
    """保存当前程序的最新活跃时间戳"""
    get_db_manager().set_last_exit_ts(ts)


def db_get_source_last_ts(source_name: str) -> int:
    """获取指定源的增量时间戳"""
    return get_db_manager().get_source_last_ts(source_name)


def db_set_source_last_ts(source_name: str, ts: int):
    """保存指定源的增量时间戳"""
    get_db_manager().set_source_last_ts(source_name, ts)


def db_get_all_source_last_ts() -> Dict[str, int]:
    """获取所有源的增量时间戳"""
    return get_db_manager().get_all_source_last_ts()


def db_get_metadata(key: str, default: str = "") -> str:
    """获取元数据"""
    return get_db_manager().get_metadata(key, default)


def db_set_metadata(key: str, value: str):
    """设置元数据"""
    get_db_manager().set_metadata(key, value)


def db_mark_read(news_id: int, is_read: bool = True):
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