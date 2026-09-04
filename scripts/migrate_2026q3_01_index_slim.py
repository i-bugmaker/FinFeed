#!/usr/bin/env python
"""架构迁移 2026Q3-01：索引瘦身与孤儿表清理（可重复执行）。

背景（docs/ARCHITECTURE_REVIEW.md §5）：
  - news 表挂 22 个索引，其中 12 个冗余：
      * 3 组逐字重复：idx_pubts_id / idx_publish_ts ≡ idx_pubts；
        idx_fav_pubts ≡ idx_fav_ts；idx_source_pubts ≡ idx_source_ts
      * 4 个单列索引是复合索引的最左前缀：idx_sentiment/idx_favorite/
        idx_importance/idx_source
      * 4 个无任何查询谓词使用：idx_url_hash / idx_title_full_hash /
        idx_unread / idx_created（全仓 grep 证实零引用）
  - board_snapshots 329 万行、零索引，大屏查询全表扫描 → 加 (ts, code)
  - event_stock_link 8.4 万行、全仓零代码引用 → 孤儿表，删除

安全措施：
  * 执行前自动把目标 db 复制到同目录 *.pre_migrate.bak
  * 全部语句幂等（IF EXISTS / IF NOT EXISTS / 存在性判断）
  * --vacuum 可选：离线回收文件空间（服务运行中勿用，VACUUM 需独占）

用法：
  python scripts/migrate_2026q3_01_index_slim.py            # 执行迁移
  python scripts/migrate_2026q3_01_index_slim.py --dry-run  # 只打印计划
  python scripts/migrate_2026q3_01_index_slim.py --vacuum   # 迁移后离线 VACUUM
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_DB = os.path.join(ROOT, "finfeed", "news_monitor.db")
CAPITAL_DB = os.path.join(ROOT, "logs", "capital_flow.db")

# 保留 10 个：url_source(唯一)/simhash/title_hash/pubts/source_ts/
# category_ts/fav_ts/composite/imp_pubts/sent_pubts
DROP_NEWS_INDEXES = [
    "idx_pubts_id",        # ≡ idx_pubts
    "idx_publish_ts",      # ≡ idx_pubts
    "idx_fav_pubts",       # ≡ idx_fav_ts
    "idx_source_pubts",    # ≡ idx_source_ts
    "idx_sentiment",       # idx_sent_pubts 最左前缀
    "idx_favorite",        # idx_fav_ts 最左前缀
    "idx_importance",      # idx_imp_pubts 最左前缀
    "idx_source",          # idx_source_ts 最左前缀
    "idx_url_hash",        # 无查询使用
    "idx_title_full_hash", # 无查询使用
    "idx_unread",          # 无查询使用（仅 UPDATE，无 WHERE is_read）
    "idx_created",         # 无查询使用
]


def log(msg: str) -> None:
    print(f"[migrate] {msg}", flush=True)


def backup(path: str, dry: bool) -> None:
    if not os.path.exists(path):
        log(f"跳过备份（文件不存在）: {path}")
        return
    bak = path + ".pre_migrate.bak"
    if os.path.exists(bak):
        log(f"备份已存在，跳过: {bak}")
        return
    if dry:
        log(f"[dry-run] 将备份 {path} -> {bak}")
        return
    t0 = time.time()
    shutil.copy2(path, bak)
    log(f"备份完成: {bak} ({os.path.getsize(bak) / 1e6:.0f} MB, {time.time() - t0:.1f}s)")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def index_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone() is not None


def migrate_news(dry: bool) -> None:
    log(f"--- news_monitor.db: {NEWS_DB}")
    backup(NEWS_DB, dry)
    if not os.path.exists(NEWS_DB):
        log("库不存在，跳过")
        return
    conn = connect(NEWS_DB)
    try:
        before = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='news'")]
        dropped = 0
        for name in DROP_NEWS_INDEXES:
            if not index_exists(conn, name):
                continue
            if dry:
                log(f"[dry-run] DROP INDEX {name}")
            else:
                conn.execute(f"DROP INDEX IF EXISTS {name}")
                log(f"DROP INDEX {name}")
            dropped += 1
        # 孤儿表：全仓零代码引用（grep 证实），数据已随备份保留
        if table_exists(conn, "event_stock_link"):
            if dry:
                log("[dry-run] DROP TABLE event_stock_link")
            else:
                conn.execute("DROP TABLE IF EXISTS event_stock_link")
                log("DROP TABLE event_stock_link（孤儿表，83,718 行已在备份中保留）")
        if not dry:
            conn.commit()
        after = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='news'")]
        log(f"news 索引: {len(before)} -> {len(after)}（本次删除 {dropped}）")
    finally:
        conn.close()


def migrate_capital(dry: bool) -> None:
    log(f"--- capital_flow.db: {CAPITAL_DB}")
    backup(CAPITAL_DB, dry)
    if not os.path.exists(CAPITAL_DB):
        log("库不存在，跳过")
        return
    conn = connect(CAPITAL_DB)
    try:
        if not table_exists(conn, "board_snapshots"):
            log("board_snapshots 不存在，跳过")
            return
        if index_exists(conn, "idx_board_ts_code"):
            log("idx_board_ts_code 已存在，跳过")
            return
        n = conn.execute("SELECT COUNT(*) FROM board_snapshots").fetchone()[0]
        if dry:
            log(f"[dry-run] CREATE INDEX idx_board_ts_code（现 {n} 行）")
            return
        t0 = time.time()
        conn.execute("CREATE INDEX IF NOT EXISTS idx_board_ts_code ON board_snapshots(ts, code)")
        conn.commit()
        log(f"CREATE INDEX idx_board_ts_code 完成（{n} 行，{time.time() - t0:.1f}s）")
    finally:
        conn.close()


def vacuum(dry: bool) -> None:
    """离线回收空间：需服务停止（VACUUM 要求独占访问）。"""
    for path in (NEWS_DB, CAPITAL_DB):
        if not os.path.exists(path):
            continue
        before_mb = os.path.getsize(path) / 1e6
        if dry:
            log(f"[dry-run] VACUUM {path}（当前 {before_mb:.0f} MB）")
            continue
        log(f"VACUUM {path}（当前 {before_mb:.0f} MB）…")
        t0 = time.time()
        conn = connect(path)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
        after_mb = os.path.getsize(path) / 1e6
        log(f"  {before_mb:.0f} MB -> {after_mb:.0f} MB（释放 {before_mb - after_mb:.0f} MB，{time.time() - t0:.0f}s）")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不修改")
    ap.add_argument("--vacuum", action="store_true", help="迁移后执行 VACUUM（需服务离线）")
    args = ap.parse_args()

    log(f"模式: {'DRY-RUN' if args.dry_run else 'EXECUTE'}")
    migrate_news(args.dry_run)
    migrate_capital(args.dry_run)
    if args.vacuum:
        vacuum(args.dry_run)
    log("完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
