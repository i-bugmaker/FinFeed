"""Schema 版本化迁移框架（PRAGMA user_version）。

架构评估 §6：此前 47 处 CREATE TABLE 散落 12 个文件、零版本管理，改表结构
等于赌旧库兼容。本模块建立唯一权威的迁移序列：

规则：
  1. 存量表结构由各模块的 CREATE TABLE IF NOT EXISTS 创建（已冻结，不再演进），
     记为基线 v1 —— 基线不做任何操作，仅打版本戳。
  2. 此后**所有** schema 变更（新表/新列/索引/数据回填）必须新增一个迁移项，
     递增版本号，且必须幂等（可重复执行）。
  3. 迁移按版本顺序执行；user_version 落后几个版本就补几个。
  4. 不允许修改已发布的迁移项（包括 v1），只允许追加。

用法（唯一调用方：storage.database.NewsDatabase.init_db）：

    from finfeed.storage.schema_migrations import apply_migrations
    applied = apply_migrations(conn)   # 返回本次实际执行的版本列表

人工排查：

    python -m finfeed.storage.schema_migrations   # 打印各库当前版本
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)

# 孤儿/冗余索引清理（详见 scripts/migrate_2026q3_01_index_slim.py）。
# 已于 2026-09-04 在生产库执行；此处登记保证其他环境（新装/备份恢复）同步收敛。
_INDEX_SLIM_DROPS = [
    "idx_pubts_id", "idx_publish_ts", "idx_fav_pubts", "idx_source_pubts",
    "idx_sentiment", "idx_favorite", "idx_importance", "idx_source",
    "idx_url_hash", "idx_title_full_hash", "idx_unread", "idx_created",
]


def _migration_v1_baseline(c: sqlite3.Cursor) -> None:
    """基线：存量表由 CREATE TABLE IF NOT EXISTS 创建，此处仅打版本戳。"""
    # 刻意为空 —— 新装库与存量库在此汇合，后续迁移对两者一视同仁。


def _migration_v2_index_slim(c: sqlite3.Cursor) -> None:
    """news 表冗余索引清理：22 -> 10（3 组重复 + 4 前缀冗余 + 4 零引用）。"""
    for name in _INDEX_SLIM_DROPS:
        c.execute(f"DROP INDEX IF EXISTS {name}")
    # 孤儿表（全仓零代码引用）
    c.execute("DROP TABLE IF EXISTS event_stock_link")


def _migration_v3_margin_code_index(c: sqlite3.Cursor) -> None:
    """margin_detail 补 (code, trade_date) 索引。

    原有唯一键为 (trade_date, code)，`WHERE code=? ORDER BY trade_date DESC`
    无法命中（code 非最左列），个股档案查询在 7 万行上全表扫描。
    """
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_margin_code_ts ON margin_detail(code, trade_date)"
    )


Migration = Tuple[int, str, Callable[[sqlite3.Cursor], None]]

MIGRATIONS: List[Migration] = [
    (1, "baseline_2026q3", _migration_v1_baseline),
    (2, "index_slim_2026q3", _migration_v2_index_slim),
    (3, "margin_code_index_2026q3", _migration_v3_margin_code_index),
]

LATEST_VERSION = MIGRATIONS[-1][0]


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def apply_migrations(conn: sqlite3.Connection) -> List[int]:
    """按序执行未应用的迁移，返回本次实际执行的版本号列表。"""
    from_version = current_version(conn)
    if from_version >= LATEST_VERSION:
        return []

    applied: List[int] = []
    for version, name, fn in MIGRATIONS:
        if version <= from_version:
            continue
        try:
            fn(conn.cursor())
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
            applied.append(version)
            logger.info(f"schema 迁移 v{version} ({name}) 完成")
        except sqlite3.Error as e:
            logger.error(f"schema 迁移 v{version} ({name}) 失败: {e}")
            break  # 中断后续迁移，保持 user_version 停在最后成功版本
    return applied


if __name__ == "__main__":
    from finfeed.config.settings import DB_PATH
    from finfeed.storage.connect import connect

    conn = connect(DB_PATH)
    v = current_version(conn)
    print(f"{DB_PATH}")
    print(f"  当前 schema 版本: v{v} / 最新 v{LATEST_VERSION}")
    for version, name, _fn in MIGRATIONS:
        mark = "已应用" if version <= v else "未应用"
        print(f"  v{version:<3} {name:24s} {mark}")
    conn.close()
