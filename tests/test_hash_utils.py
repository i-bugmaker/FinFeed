#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""哈希与去重工具函数单元测试（纯逻辑、无网络、无数据库）

覆盖 finfeed/utils/hash_utils.py 的全部纯逻辑函数，锁定以下回归行为：

- normalize_title 标题标准化：
  全角转半角（NFKC）、已知来源前缀剥离（"财联社：xxx" / "财联社|xxx" / "财联社讯 xxx"）、
  【xxx】/ [xxx] 前缀剥离、|来源后缀剥离、URL 剥离、数字中小数点/逗号归一化
  （"0.5个百分点"->"05个百分点"）、全部标点与空白去除、统一小写。
  历史缺陷：来源前缀剥离不彻底，导致同一新闻跨源标题哈希不一致（"财联社：A股大涨"
  与 "A股大涨" 此前哈希不同），L2 跨源精确去重失效。现两者 normalize 后均为 "a股大涨"。
- compute_normalized_title_hash / compute_title_full_hash / compute_url_hash：MD5 固定值。
- compute_simhash：字符 n-gram 简化 SimHash（无分词库依赖）；空/过短文本返回 0；
  相同文本哈希一致且汉明距离为 0；完全不同文本的汉明距离远大于 SIMHASH_THRESHOLD。
- simhash_to_hex / hex_to_simhash 往返一致；非法输入返回 0。
- hamming_distance / is_semantic_duplicate 的精确计算。

运行: python -m pytest tests/test_hash_utils.py -q
"""

import pytest

from finfeed.utils import hash_utils as hu
from finfeed.config.settings import SIMHASH_THRESHOLD


class TestNormalizeTitle:
    """标题标准化：全角转半角、去来源前缀、去标点、去URL、数字归一化"""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            # 空输入
            ("", ""),
            ("   ", ""),
            (None, ""),
            # 普通标题：统一小写、去除空白
            ("A股大涨", "a股大涨"),
            # 全角转半角（NFKC）
            ("Ａ股大涨１２３", "a股大涨123"),
            # 来源前缀剥离（冒号 / 竖线 / 「讯」后缀）
            ("财联社：A股大涨", "a股大涨"),
            ("财联社|A股大涨", "a股大涨"),
            ("财联社讯 A股大涨", "a股大涨"),
            ("财联社讯：A股大涨", "a股大涨"),
            ("新浪财经：沪指翻红", "沪指翻红"),
            ("每经网|A股大涨", "a股大涨"),
            # 纯来源名保留主体（"东方财富" 不在前缀列表中剥离成空）
            ("东方财富", "东方财富"),
            # 【】与 [] 前缀剥离
            ("【重磅】A股大涨", "a股大涨"),
            ("[公告]A股大涨", "a股大涨"),
            # | 来源后缀剥离
            ("A股大涨|来源财联社", "a股大涨"),
            # URL 剥离
            ("A股大涨 http://example.com/news/123", "a股大涨"),
            # 标点去除
            ("A股大涨，沪指翻红！", "a股大涨沪指翻红"),
            # 数字中小数点/逗号归一化
            ("0.5个百分点", "05个百分点"),
            ("1,000亿市值", "1000亿市值"),
            ("上涨0.5%", "上涨05"),
            # 组合场景
            ("财联社：0.5个百分点 1,000亿", "05个百分点1000亿"),
        ],
    )
    def test_normalize_title(self, raw, expected):
        assert hu.normalize_title(raw) == expected

    def test_cross_source_normalize_equality(self):
        """跨源同一条新闻标准化后一致（L2 去重前提）"""
        assert hu.normalize_title("财联社：A股大涨") == hu.normalize_title("A股大涨")

    def test_normalize_removes_all_whitespace(self):
        """标准化结果不含任何空白字符"""
        out = hu.normalize_title("A股  大涨 \t 沪指翻红")
        assert " " not in out and "\t" not in out and "\n" not in out


class TestTitleHash:
    """标题 MD5 哈希"""

    def test_normalized_hash_known_constant(self):
        # MD5("a股大涨") 的固定值，锁定跨源 L2 去重哈希
        assert hu.compute_normalized_title_hash("A股大涨") == "bb2a894f1cbc898c7f28d3cccd6e7c4b"

    def test_normalized_hash_cross_source_consistent(self):
        assert (
            hu.compute_normalized_title_hash("财联社：A股大涨")
            == hu.compute_normalized_title_hash("A股大涨")
            == "bb2a894f1cbc898c7f28d3cccd6e7c4b"
        )

    def test_normalized_hash_empty(self):
        assert hu.compute_normalized_title_hash("") == ""
        assert hu.compute_normalized_title_hash("  。。 ") == ""

    def test_full_hash_known_constant(self):
        assert hu.compute_title_full_hash("hello") == "5d41402abc4b2a76b9719d911017c592"
        assert len(hu.compute_title_full_hash("任意标题")) == 32  # MD5 恒为 32 位 hex

    def test_url_hash(self):
        assert hu.compute_url_hash("http://example.com/a") == "3e27a17e84f5f8486fbc14488e12e6ff"
        assert hu.compute_url_hash("") == ""
        assert hu.compute_url_hash("#") == ""


class TestSimHash:
    """字符 n-gram SimHash"""

    def test_empty_and_short_text_zero(self):
        assert hu.compute_simhash("") == 0
        assert hu.compute_simhash(" ") == 0
        assert hu.compute_simhash(None) == 0
        assert hu.compute_simhash("a") == 0  # 长度 < 2 直接返回 0

    def test_same_text_same_hash(self):
        text = "央行宣布降准0.5个百分点释放长期资金约1万亿元"
        assert hu.compute_simhash(text) == hu.compute_simhash(text)

    def test_identical_text_zero_distance(self):
        text = "A股三大指数集体收涨"
        assert hu.hamming_distance(hu.compute_simhash(text), hu.compute_simhash(text)) == 0

    def test_different_text_larger_distance(self):
        """完全不同文本的汉明距离远大于阈值（锁定具体距离值）"""
        a = hu.compute_simhash("A股三大指数集体收涨")
        b = hu.compute_simhash("特朗普宣布新关税政策")
        dist = hu.hamming_distance(a, b)
        assert dist == 26
        assert dist > SIMHASH_THRESHOLD

    def test_highly_similar_text_small_distance(self):
        """高度相似文本距离很小（<= SIMHASH_THRESHOLD），用于 L3 去重"""
        t1 = "央行宣布降准0.5个百分点释放长期资金约1万亿元"
        t2 = "央行宣布降准0.5个百分点，释放长期资金约1万亿"
        assert hu.hamming_distance(hu.compute_simhash(t1), hu.compute_simhash(t2)) == 12
        assert hu.hamming_distance(hu.compute_simhash(t1), hu.compute_simhash(t2)) <= SIMHASH_THRESHOLD

    def test_len2_text_nonzero(self):
        # 长度为 2 的文本只产生一个 2-gram 特征，结果仍为确定性非零值
        assert hu.compute_simhash("ab") == 1765116674205471180

    def test_known_simhash_value(self):
        # 锁定固定输入的 simhash 整数值及其 hex 表示
        h = hu.compute_simhash("A股三大指数集体收涨")
        assert h == 10598477039166827513
        assert hu.simhash_to_hex(h) == "93155ab6c7ac2bf9"


class TestHexConversion:
    """SimHash 十六进制互转"""

    def test_roundtrip(self):
        for x in (0, 1, 0xDEADBEEF, 0xFFFFFFFFFFFFFFFF, 10598477039166827513):
            assert hu.hex_to_simhash(hu.simhash_to_hex(x)) == x

    def test_zero_hex(self):
        assert hu.simhash_to_hex(0) == "0000000000000000"
        assert hu.hex_to_simhash("0000000000000000") == 0

    def test_hex_length_always_16(self):
        for x in (0, 123, 2**64 - 1):
            assert len(hu.simhash_to_hex(x)) == 16

    def test_invalid_hex_returns_zero(self):
        assert hu.hex_to_simhash("") == 0
        assert hu.hex_to_simhash("zz") == 0
        assert hu.hex_to_simhash(None) == 0

    def test_negative_wraps_to_unsigned(self):
        assert hu.hex_to_simhash(hu.simhash_to_hex(-1)) == 0xFFFFFFFFFFFFFFFF


class TestHammingDistance:
    """汉明距离计算"""

    def test_known_values(self):
        assert hu.hamming_distance(0, 0) == 0
        assert hu.hamming_distance(1, 2) == 2  # 01 vs 10
        assert hu.hamming_distance(0, 0xFF) == 8
        assert hu.hamming_distance(0b1111, 0b0000) == 4

    def test_symmetry(self):
        assert hu.hamming_distance(0xFFFF, 0x0F0F) == hu.hamming_distance(0x0F0F, 0xFFFF)

    def test_within_64_bits(self):
        # 64 位全 1 与 0 的距离为 64
        assert hu.hamming_distance(0, 0xFFFFFFFFFFFFFFFF) == 64


class TestIsSemanticDuplicate:
    """语义重复判定（汉明距离 <= 阈值）"""

    def test_identical_true(self):
        assert hu.is_semantic_duplicate(0, 0) is True

    def test_distance_three_true(self):
        assert hu.is_semantic_duplicate(0, 0b111) is True

    def test_distance_four_false(self):
        assert hu.is_semantic_duplicate(0, 0b1111) is False

    def test_custom_threshold(self):
        assert hu.is_semantic_duplicate(0, 0b1111, threshold=5) is True
