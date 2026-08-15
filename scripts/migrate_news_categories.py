#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性迁移：历史 category='finance' 数据 → flash / article 两级分类。

背景
----
原「新闻流」模块把快讯与文章统一入库为 category='finance'。本次重构将
「新闻流」拆分为「快讯 flash」与「财经文章 article」两个独立模块，需要
按来源归属重标历史数据，使新端点（/api/flash、/api/articles）能按分类
精确取数。

迁移规则
--------
1. 来源展示名 ∈ 快讯展示名集合（且不在两集合交集中）→ category='flash'
2. 来源展示名 ∈ 文章展示名集合 → category='article'
3. 两集合交集来源（当前仅「格隆汇」，其快讯/文章在数据层共享同一展示名，
   历史数据无法细分）→ 统一归入 'article'（深度内容语义为主；
   新抓取数据已由解析器按内部名正确打标 flash/article，不受影响）
4. 同花顺财经/同花顺原创的历史记录曾把栏目名写入 category（如「产经新闻」
   「原创滚动盘评」）——栏目信息仍保留在 intro 的【栏目名】前缀中，
   现统一归入 'article'（二者均为文章类源）
5. 任何残留 finance 记录兜底归入 'article'（理论为空）

用法
----
python scripts/migrate_news_categories.py [--dry-run]
执行前会自动备份 news_monitor.db 到同目录 *.bak。
"""

import os
import sys
import shutil
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finfeed.config.settings import DB_PATH, get_display_name
from finfeed.config.sources import get_flash_sources, get_article_sources
from finfeed.storage.database import get_db_manager

# 曾把栏目名写入 category 的文章类栏目（见 core/parsers/json_parsers/thsyc.py、
# thsfinance.py；新数据已固定 category="article"，历史数据按栏目名归类迁移）。
# 该常量仅作说明保留；迁移规则 4 按「category 非合法模块级分类即归 article」
# 泛化处理，不依赖具体栏目名。

# category 中合法的模块级分类标签
_VALID_CATEGORIES = {"flash", "article", "forum", "finance", ""}


def _display_name_set(sources) -> set[str]:
    return {get_display_name(s.name) for s in sources}


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移历史分类为 flash/article")
    parser.add_argument("--dry-run", action="store_true", help="仅统计，不写库")
    args = parser.parse_args()

    flash_names = _display_name_set(get_flash_sources())
    article_names = _display_name_set(get_article_sources())
    overlap = flash_names & article_names
    flash_only = flash_names - overlap
    # 交集来源（格隆汇）归入 article
    article_all = article_names | overlap

    print("快讯展示名:", sorted(flash_names))
    print("文章展示名:", sorted(article_names))
    print("交集（归入文章）:", sorted(overlap))

    if not args.dry_run:
        backup = DB_PATH + ".bak"
        shutil.copy2(DB_PATH, backup)
        print(f"已备份数据库: {backup}")

    with get_db_manager().get_db() as c:
        c.execute("SELECT category, COUNT(*) AS cnt FROM news GROUP BY category ORDER BY cnt DESC")
        before = {r["category"]: r["cnt"] for r in c.fetchall()}
        print("迁移前分类分布:", before)

        if not args.dry_run:
            # 规则 1：finance + 快讯来源 → flash
            placeholders = ",".join("?" * len(flash_only))
            c.execute(
                f"UPDATE news SET category = 'flash' WHERE category = 'finance' AND source IN ({placeholders})",
                sorted(flash_only),
            )
            print(f"→ 快讯: 更新 {c.rowcount} 条")

            # 规则 2/3：finance + 文章来源（含交集格隆汇）→ article
            placeholders = ",".join("?" * len(article_all))
            c.execute(
                f"UPDATE news SET category = 'article' WHERE category = 'finance' AND source IN ({placeholders})",
                sorted(article_all),
            )
            print(f"→ 文章(finance): 更新 {c.rowcount} 条")

            # 规则 4：栏目名分类的历史记录 → article。
            # 同花顺财经/同花顺原创历史上把栏目名写入 category（如「产经新闻」
            # 「原创滚动盘评」「深度分析」等），其 source 显示名可能为
            # 「同花顺财经」「同花顺原创」或旧版「同花顺」。凡 category 不属于
            # 合法模块级分类的，一律是文章类栏目残留，归入 article
            # （栏目信息保留在 intro 的【栏目名】前缀中，不丢失）。
            c.execute(
                f"UPDATE news SET category = 'article' WHERE category NOT IN ({','.join('?' * len(_VALID_CATEGORIES))})",
                sorted(_VALID_CATEGORIES),
            )
            print(f"→ 文章(栏目名历史): 更新 {c.rowcount} 条")

            # 规则 5：任何残留 finance 兜底归入 article（理论为空）
            c.execute("UPDATE news SET category = 'article' WHERE category = 'finance'")
            print(f"→ 残留 finance 兜底归入 article: {c.rowcount} 条")

    with get_db_manager().get_db() as c:
        c.execute("SELECT category, COUNT(*) AS cnt FROM news GROUP BY category ORDER BY cnt DESC")
        after = {r["category"]: r["cnt"] for r in c.fetchall()}
    print("迁移后分类分布:", after)

    if args.dry_run:
        print("[dry-run] 未写库。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
