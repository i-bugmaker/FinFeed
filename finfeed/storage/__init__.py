"""
数据持久化模块
=============

提供数据库操作和数据导出功能。

子模块:
    - database: SQLite数据库操作
    - exporter: 数据导出（JSON/CSV/Excel/Markdown）
    - models: 数据模型定义
"""

from .database import (
    init_db, db_insert_news, db_get_recent_news, db_count_news,
    db_get_statistics, db_get_news_by_id, db_get_all_for_export,
    db_get_date_range, db_set_last_exit_ts, db_get_last_exit_ts,
    db_get_source_last_ts, db_set_source_last_ts, db_get_all_source_last_ts,
    db_get_metadata, db_set_metadata, db_mark_read, db_toggle_favorite,
    db_get_favorites, db_search_news, db_query_news, db_invalidate_stats_cache,
)
from .exporter import (
    export_to_json, export_to_csv, export_to_excel, export_to_markdown,
    get_default_export_path,
)
from .models import NewsItem