#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四级去重引擎单元测试（纯内存、无网络、无数据库）

覆盖 finfeed/core/dedup.py 的 DedupEngine 行为：

- L1 URL 精确去重；url="#" 或空串不参与 L1。
- L2 标题标准化哈希去重（跨源同一新闻，如 "财联社：A股大涨" 与 "A股大涨"）。
- L3 SimHash 语义去重（汉明距离 <= SIMHASH_THRESHOLD=18）。
- L4 时间窗(DEDUP_TIME_WINDOW=600s) + 关键词/股票 Jaccard 重合度 >=
  DEDUP_KEYWORD_OVERLAP=0.6 兜底。
- deduplicate_batch 返回 (new_items, merge_pairs, stats) 结构；
  注意实现中 stats["merged"] 恒为 0，实际待合并数应以 len(merge_pairs) 为准。
- 优先级排序：高优先级源先处理成为主记录。
- 论坛源（FORUM_DEDUP_EXEMPT）与跨源豁免源（CROSS_SOURCE_DEDUP_EXEMPT）只做 L1，
  不做 L2/L3/L4 跨源语义去重。历史缺陷：论坛/低优先级快讯源曾被高优先级源合并，
  导致独立时间线长期停滞（如法布财经停在 7-25），故豁免。
- _compute_overlap（Jaccard）与 _merge_items 的精确行为。

注意：DedupEngine 是全局单例，类属性 _instance 与模块级 _dedup_engine
必须同时重置，否则测试间窗口/索引/统计串扰。

运行: python -m pytest tests/test_dedup.py -q
"""

import time

import pytest

import finfeed.core.dedup as dedup_mod
from finfeed.storage.models import NewsItem
from finfeed.config.settings import (
    SIMHASH_THRESHOLD,
    DEDUP_TIME_WINDOW,
    DEDUP_KEYWORD_OVERLAP,
)
from finfeed.utils.hash_utils import compute_simhash, hamming_distance


# 固定内容 simhash 为 0（十六进制 "0"），用于强制跳过 L3、只测 L4
_SENTINEL_SIMHASH = "0000000000000000"


@pytest.fixture(autouse=True)
def reset_singletons():
    """每个测试前/后重置两个全局单例，保证测试完全隔离。"""
    dedup_mod.DedupEngine._instance = None
    dedup_mod._dedup_engine = None
    yield
    dedup_mod.DedupEngine._instance = None
    dedup_mod._dedup_engine = None


def _mk(title, url="#", source="财联社", ts=None, **kw):
    """构造测试用 NewsItem；publish_ts 默认取当前时间保证落在去重窗口内。"""
    return NewsItem(
        title=title,
        url=url,
        source=source,
        publish_ts=int(time.time()) if ts is None else ts,
        **kw,
    )


def _fresh_engine():
    return dedup_mod.DedupEngine()


class TestSingleton:
    """单例与全局句柄的重置语义"""

    def test_get_dedup_engine_returns_same_instance(self):
        e1 = dedup_mod.get_dedup_engine()
        e2 = dedup_mod.get_dedup_engine()
        assert e1 is e2
        assert dedup_mod.DedupEngine._instance is e1

    def test_reset_creates_fresh_instance(self):
        """重置 _instance 后新建实例不共享旧状态"""
        e1 = dedup_mod.get_dedup_engine()
        dedup_mod.DedupEngine._instance = None
        e2 = dedup_mod.DedupEngine()
        assert e2 is not e1
        assert len(e2._window) == 0


class TestL1UrlDedup:
    """L1：URL 精确去重"""

    def test_same_url_dedup(self):
        eng = _fresh_engine()
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk("标题甲", url="http://e.com/a"),
            _mk("标题乙", url="http://e.com/a", source="金十数据"),
        ])
        assert len(new_items) == 1
        assert len(merge_pairs) == 1
        assert stats["l1"] == 1
        assert stats["duplicate"] == 1
        assert stats["new"] == 1
        assert merge_pairs[0][0].source == "金十数据"  # 被合并的是后处理的低优先级源
        assert merge_pairs[0][1].id == 0  # 主记录 ID 为占位 0

    def test_hash_url_ignored(self):
        """url="#" 与空串不参与 L1 索引，也不触发 L1 命中"""
        eng = _fresh_engine()
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk("标题甲", url="#"),
            _mk("标题乙", url="#", source="金十数据"),
            _mk("标题丙", url="", source="新浪财经"),
        ])
        assert len(new_items) == 3
        assert len(merge_pairs) == 0
        assert stats["l1"] == 0
        assert stats["new"] == 3


class TestL2TitleHashDedup:
    """L2：标准化标题哈希跨源去重"""

    def test_cross_source_same_normalized_title(self):
        eng = _fresh_engine()
        items = [
            _mk("财联社：A股大涨", url="http://e.com/1"),
            _mk("A股大涨", url="http://e.com/2", source="新浪财经"),
        ]
        new_items, merge_pairs, stats = eng.deduplicate_batch(items)
        assert stats["l2"] == 1
        assert stats["duplicate"] == 1
        assert len(merge_pairs) == 1
        assert merge_pairs[0][0].source == "新浪财经"
        assert merge_pairs[0][1].source == "财联社"  # 主记录为高优先级源
        # 标题哈希被自动计算且锁定为已知常量
        assert items[0].title_hash == "bb2a894f1cbc898c7f28d3cccd6e7c4b"
        assert items[0].title_hash == items[1].title_hash


class TestL3SimHashDedup:
    """L3：SimHash 语义去重"""

    def test_highly_similar_text_dedup(self):
        t1 = "央行宣布降准0.5个百分点释放长期资金约1万亿元"
        t2 = "央行宣布降准0.5个百分点，释放长期资金约1万亿"
        # 前置条件：两个标题的 simhash 距离 <= 阈值（intro 为空时内容即标题）
        dist = hamming_distance(compute_simhash(t1), compute_simhash(t2))
        assert dist == 12
        assert dist <= SIMHASH_THRESHOLD

        eng = _fresh_engine()
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk(t1, url="http://e.com/3"),
            _mk(t2, url="http://e.com/4", source="金十数据"),
        ])
        assert stats["l3"] == 1
        assert stats["l2"] == 0  # 标题哈希不同，未触发 L2
        assert len(new_items) == 1
        assert len(merge_pairs) == 1
        assert merge_pairs[0][1].source == "财联社"


class TestL4TimeKeywordDedup:
    """L4：时间窗 + 关键词/股票重合兜底"""

    def test_keyword_overlap_dedup(self):
        eng = _fresh_engine()
        kw = ["三季报", "净利润", "同比增长"]
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk("A公司发布三季报净利润同比增长50%", url="http://e.com/5",
                keywords=kw, content_simhash=_SENTINEL_SIMHASH),
            _mk("某公司晚间公告三季度财报盈利大增", url="http://e.com/6", source="金十数据",
                keywords=kw, content_simhash=_SENTINEL_SIMHASH),
        ])
        assert stats["l4"] == 1
        assert stats["l3"] == 0  # simhash 为 0 被跳过，只走 L4
        assert len(merge_pairs) == 1
        assert len(new_items) == 1

    def test_stock_overlap_dedup(self):
        """关键词完全不重合但股票完全重合，同样命中 L4"""
        eng = _fresh_engine()
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk("标题甲", url="http://e.com/7", stocks=["600000"],
                content_simhash=_SENTINEL_SIMHASH),
            _mk("标题乙", url="http://e.com/8", source="金十数据", stocks=["600000"],
                content_simhash=_SENTINEL_SIMHASH),
        ])
        assert stats["l4"] == 1
        assert len(merge_pairs) == 1

    def test_below_overlap_threshold_not_dedup(self):
        """关键词重合度低于 0.6 不触发 L4"""
        eng = _fresh_engine()
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk("标题甲", url="http://e.com/9", keywords=["a", "b"],
                content_simhash=_SENTINEL_SIMHASH),
            _mk("标题乙", url="http://e.com/10", source="金十数据", keywords=["c", "d"],
                content_simhash=_SENTINEL_SIMHASH),
        ])
        assert stats["l4"] == 0
        assert stats["new"] == 2
        assert len(merge_pairs) == 0

    def test_outside_time_window_not_dedup(self):
        """超出 600s 时间窗即使关键词完全相同也不触发 L4"""
        eng = _fresh_engine()
        kw = ["三季报", "净利润", "同比增长"]
        now = int(time.time())
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk("A公司发布三季报净利润同比增长50%", url="http://e.com/11", ts=now,
                keywords=kw, content_simhash=_SENTINEL_SIMHASH),
            _mk("某公司晚间公告三季度财报盈利大增", url="http://e.com/12", source="金十数据",
                ts=now - DEDUP_TIME_WINDOW - 1,  # 窗口外 601 秒
                keywords=kw, content_simhash=_SENTINEL_SIMHASH),
        ])
        assert stats["l4"] == 0
        assert stats["new"] == 2
        assert len(merge_pairs) == 0


class TestComputeOverlap:
    """Jaccard 重合度计算"""

    def test_empty_sets_zero(self):
        eng = _fresh_engine()
        assert eng._compute_overlap(set(), set()) == 0.0
        assert eng._compute_overlap({"a"}, set()) == 0.0
        assert eng._compute_overlap(set(), {"a"}) == 0.0

    def test_identical_sets_one(self):
        eng = _fresh_engine()
        assert eng._compute_overlap({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets_zero(self):
        eng = _fresh_engine()
        assert eng._compute_overlap({"x"}, {"y"}) == 0.0

    def test_partial_overlap_half(self):
        eng = _fresh_engine()
        # 交集 {b,c}=2，并集 {a,b,c,d}=4，Jaccard=0.5
        assert eng._compute_overlap({"a", "b", "c"}, {"b", "c", "d"}) == 0.5


class TestBatchStructure:
    """deduplicate_batch 返回值结构与统计"""

    def test_return_structure_types(self):
        eng = _fresh_engine()
        result = eng.deduplicate_batch([_mk("标题甲", url="http://e.com/u0")])
        assert isinstance(result, tuple) and len(result) == 3
        new_items, merge_pairs, stats = result
        assert isinstance(new_items, list)
        assert all(isinstance(i, NewsItem) for i in new_items)
        assert isinstance(merge_pairs, list)
        assert all(isinstance(p, tuple) and len(p) == 2
                   and isinstance(p[0], NewsItem) and isinstance(p[1], NewsItem)
                   for p in merge_pairs)
        assert isinstance(stats, dict)
        assert set(stats.keys()) == {"total", "l1", "l2", "l3", "l4", "new", "merged", "duplicate"}

    def test_combined_four_levels_stats(self):
        """一次批量同时命中 L1/L2/L3/L4，锁定精确统计值"""
        eng = _fresh_engine()
        kw = ["三季报", "净利润", "同比增长"]
        t1 = "央行宣布降准0.5个百分点释放长期资金约1万亿元"
        t2 = "央行宣布降准0.5个百分点，释放长期资金约1万亿"
        items = [
            _mk(t1, url="http://e.com/u1", source="财联社"),
            _mk(t2, url="http://e.com/u2", source="金十数据"),  # L3 命中
            _mk("财联社：A股大涨", url="http://e.com/u3", source="新浪财经"),
            _mk("A股大涨", url="http://e.com/u4", source="同花顺"),  # L2 命中
            _mk("完全不同的标题", url="http://e.com/u1", source="新华财经"),  # L1 命中
            _mk("A公司发布三季报净利润同比增长50%", url="http://e.com/u5", source="财联社",
                keywords=kw, content_simhash=_SENTINEL_SIMHASH),
            _mk("某公司晚间公告三季度财报盈利大增", url="http://e.com/u6", source="金十数据",
                keywords=kw, content_simhash=_SENTINEL_SIMHASH),  # L4 命中
        ]
        new_items, merge_pairs, stats = eng.deduplicate_batch(items)

        assert stats == {
            "total": 7, "l1": 1, "l2": 1, "l3": 1, "l4": 1,
            "new": 3, "merged": 0, "duplicate": 4,
        }
        # 实现细节：merged 恒为 0，实际待合并数看 len(merge_pairs)
        assert stats["merged"] == 0
        assert len(merge_pairs) == stats["duplicate"] == 4
        assert len(new_items) == 3
        # 主记录源按优先级保留（财联社 100 > 金十 98 > 新浪 90 > 同花顺 86）
        assert sorted(p[1].source for p in merge_pairs) == sorted(
            ["财联社", "财联社", "财联社", "新浪财经"]
        )
        # 新条目自动补全 title_hash 与 content_simhash
        assert all(i.title_hash for i in new_items)
        assert all(i.content_simhash for i in new_items)

    def test_stats_accumulation(self):
        """引擎级 _stats 跨批次累计"""
        eng = _fresh_engine()
        eng.deduplicate_batch([_mk("标题甲", url="http://e.com/x1")])
        eng.deduplicate_batch([_mk("标题乙", url="http://e.com/x2", source="金十数据")])
        assert eng.get_stats() == {"l1_hits": 0, "l2_hits": 0, "l3_hits": 0, "l4_hits": 0, "new_items": 2}

    def test_reset_stats(self):
        eng = _fresh_engine()
        eng.deduplicate_batch([_mk("标题甲", url="http://e.com/x1")])
        eng.reset_stats()
        assert eng.get_stats() == {"l1_hits": 0, "l2_hits": 0, "l3_hits": 0, "l4_hits": 0, "new_items": 0}


class TestPriorityOrdering:
    """优先级排序：高优先级源先处理成为主记录"""

    def test_high_priority_source_is_primary(self):
        eng = _fresh_engine()
        # 批次按低优先级在前传入，处理时应先处理高优先级（新浪财经 90 > 每经网 70）
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk("A股大涨", url="http://e.com/p1", source="每经网"),
            _mk("A股大涨", url="http://e.com/p2", source="新浪财经"),
        ])
        assert stats["l2"] == 1
        assert len(new_items) == 1
        assert new_items[0].source == "新浪财经"  # 高优先级成为主记录
        assert merge_pairs[0][0].source == "每经网"  # 低优先级被合并
        assert merge_pairs[0][1].source == "新浪财经"


class TestSourceIsolation:
    """论坛源与跨源豁免源只做 L1，不做 L2/L3/L4"""

    def test_forum_source_not_cross_source_dedup(self):
        """论坛源（雪球）与新闻源同标题不触发 L2"""
        eng = _fresh_engine()
        eng.deduplicate_batch([_mk("A股大涨", url="http://e.com/f1", source="财联社")])
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk("A股大涨", url="http://e.com/f2", source="雪球"),
        ])
        assert stats["l2"] == 0
        assert stats["new"] == 1
        assert len(merge_pairs) == 0

    def test_forum_source_still_l1_url_dedup(self):
        """论坛源仍做 L1 URL 精确去重"""
        eng = _fresh_engine()
        eng.deduplicate_batch([_mk("标题甲", url="http://e.com/f3", source="财联社")])
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk("标题乙", url="http://e.com/f3", source="雪球"),
        ])
        assert stats["l1"] == 1
        assert len(merge_pairs) == 1

    def test_cross_source_exempt_source_not_dedup(self):
        """豁免源（法布财经）与新闻源同标题不触发 L2（保留独立时间线）"""
        eng = _fresh_engine()
        eng.deduplicate_batch([_mk("A股大涨", url="http://e.com/f4", source="财联社")])
        new_items, merge_pairs, stats = eng.deduplicate_batch([
            _mk("A股大涨", url="http://e.com/f5", source="法布财经"),
        ])
        assert stats["l2"] == 0
        assert stats["new"] == 1
        assert len(merge_pairs) == 0


class TestMergeItems:
    """_merge_items：重复条目元数据合并"""

    def test_full_merge(self):
        eng = _fresh_engine()
        existing = NewsItem(
            title="A", url="u1", source="新浪财经", publish_ts=200, publish_time="t200",
            intro="short", keywords=["a", "b"], stocks=["600000"], importance=3.0,
            duplicate_sources=["东方财富"], duplicate_count=0,
        )
        new = NewsItem(
            title="B", url="u2", source="财联社", publish_ts=100, publish_time="t100",
            intro="a much longer intro here", keywords=["b", "c"], stocks=["000001"], importance=5.0,
        )
        ret = eng._merge_items(existing, new)
        assert ret is existing  # 原地合并并返回主记录
        assert sorted(existing.duplicate_sources) == ["东方财富", "新浪财经", "财联社"]
        assert existing.duplicate_count == 2  # len(源列表) - 1
        assert existing.intro == "a much longer intro here"  # 更长的摘要替换
        assert existing.publish_ts == 100 and existing.publish_time == "t100"  # 更早时间替换
        assert sorted(existing.stocks) == ["000001", "600000"]  # 股票取并集
        assert sorted(existing.keywords) == ["a", "b", "c"]  # 关键词取并集
        assert existing.importance == 5.0  # 更高重要性替换
        assert existing._needs_update is True
        assert existing._merge_with_id == existing.id  # 主记录自身 id

    def test_keep_primary_when_new_inferior(self):
        """新条目摘要更短/时间更晚/重要性更低时保留主记录原值，股票仍取并集"""
        eng = _fresh_engine()
        existing = NewsItem(
            title="X", source="财联社", publish_ts=100, publish_time="t100",
            intro="longer intro here", keywords=["a"], stocks=["600000"], importance=5.0,
        )
        new = NewsItem(
            title="Y", source="金十数据", publish_ts=300, publish_time="t300",
            intro="s", keywords=["a", "b"], stocks=["000001"], importance=2.0,
        )
        eng._merge_items(existing, new)
        assert existing.intro == "longer intro here"
        assert existing.publish_ts == 100 and existing.publish_time == "t100"
        assert existing.importance == 5.0
        assert sorted(existing.stocks) == ["000001", "600000"]
        assert sorted(existing.keywords) == ["a", "b"]

    def test_duplicate_count_starts_zero(self):
        """主记录无历史重复源时，合并后 duplicate_count == 1"""
        eng = _fresh_engine()
        existing = NewsItem(title="A", source="财联社", publish_ts=1)
        new = NewsItem(title="B", source="金十数据", publish_ts=2)
        eng._merge_items(existing, new)
        assert sorted(existing.duplicate_sources) == ["财联社", "金十数据"]
        assert existing.duplicate_count == 1
