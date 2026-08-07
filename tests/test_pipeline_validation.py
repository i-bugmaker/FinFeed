#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""管道字段清洗与校验单元测试（纯逻辑、无网络、无数据库）

覆盖 finfeed/core/pipeline.py 的纯逻辑函数（不调用 process_news_items，
因此不触发任何网络/数据库/分析器副作用）：

- _clean_title：空值安全、折叠连续空白；不做标点/大小写/来源前缀处理
  （该职责在 hash_utils.normalize_title）。
- _clean_intro：剥离 HTML 标签、折叠空白、超过 500 字符截断为 500 + "..."。
- _validate_stocks：支持 60xxxx / 688xxx / 00xxxx / 30xxxx / 8xxxxx / 4xxxxx
  及 SH/SZ/BJ 前缀；小写前缀（sh600000）、长度错误（60000/6000000）、
  纯数字不匹配（123456）等被过滤；去除空白与重复项。
  历史行为：BJ 前缀分支只接受 [036] 开头代码，故 "BJ430047" 不匹配
  （裸码 "430047" 走 ^[48][0-9]{5}$ 分支才能通过）。
- _validate_timestamp：ts<=0、超过未来 1 天（now+86400 之后）、早于
  2000-01-01（946656000）的非法值统一回落到当前时间；正常值原样保留。
  使用 monkeypatch 固定 time.time() 保证确定性。

运行: python -m pytest tests/test_pipeline_validation.py -q
"""

import pytest

import finfeed.core.pipeline as pipeline_mod


class TestCleanTitle:
    """标题清洗：空值安全 + 空白折叠"""

    def test_empty(self):
        assert pipeline_mod._clean_title("") == ""
        assert pipeline_mod._clean_title(None) == ""

    def test_collapse_whitespace(self):
        assert pipeline_mod._clean_title("  A股  大涨  ") == "A股 大涨"
        assert pipeline_mod._clean_title("A股\n\t大涨") == "A股 大涨"

    def test_normal_title_unchanged(self):
        assert pipeline_mod._clean_title("A股大涨") == "A股大涨"

    def test_no_punctuation_stripping(self):
        """_clean_title 不删标点（标点归一化属于 hash_utils.normalize_title）"""
        assert pipeline_mod._clean_title("A股大涨，沪指翻红！") == "A股大涨，沪指翻红！"


class TestCleanIntro:
    """摘要清洗：去 HTML 标签 + 空白折叠 + 500 字符截断"""

    def test_empty(self):
        assert pipeline_mod._clean_intro("") == ""
        assert pipeline_mod._clean_intro(None) == ""

    def test_strip_html_tags(self):
        assert pipeline_mod._clean_intro("<p>内容A</p>  <p>内容B</p>") == "内容A 内容B"
        assert pipeline_mod._clean_intro("<div class='x'>A股大涨</div>") == "A股大涨"

    def test_collapse_whitespace(self):
        assert pipeline_mod._clean_intro("第一段\n\n  第二段") == "第一段 第二段"

    def test_truncate_over_500(self):
        long_intro = "x" * 501
        out = pipeline_mod._clean_intro(long_intro)
        assert len(out) == 503  # 500 + "..."
        assert out == "x" * 500 + "..."

    def test_keep_at_500(self):
        intro = "y" * 500
        assert pipeline_mod._clean_intro(intro) == intro  # 恰好 500 不截断

    def test_plain_text_kept(self):
        assert pipeline_mod._clean_intro("这是一条普通摘要") == "这是一条普通摘要"


class TestValidateStocks:
    """股票代码格式校验：前缀、去重、去空"""

    def test_empty(self):
        assert pipeline_mod._validate_stocks(None) == []
        assert pipeline_mod._validate_stocks([]) == []
        assert pipeline_mod._validate_stocks([""]) == []

    def test_valid_codes(self):
        raw = ["600000", "688981", "000001", "300750", "831010", "430047",
               "SH600000", "SZ000001"]
        assert pipeline_mod._validate_stocks(raw) == raw

    def test_invalid_codes_filtered(self):
        raw = ["sh600000", "123456", "60000", "6000000", "abcdef", "BJ430047"]
        assert pipeline_mod._validate_stocks(raw) == []

    def test_deduplicate(self):
        assert pipeline_mod._validate_stocks(["600000", "600000", "000001"]) == ["600000", "000001"]

    def test_strip_whitespace(self):
        assert pipeline_mod._validate_stocks([" 600000 ", "\t000001\n"]) == ["600000", "000001"]

    def test_mixed_valid_and_invalid(self):
        raw = ["600000", "bad", "", "  ", "300750", "999999"]
        assert pipeline_mod._validate_stocks(raw) == ["600000", "300750"]


class TestValidateTimestamp:
    """时间戳校验：非法值回落当前时间，正常值保留"""

    FIXED_NOW = 1_700_000_000
    # 2000-01-01T00:00:00Z
    EPOCH_2000 = 946656000

    @pytest.fixture(autouse=True)
    def _freeze_time(self, monkeypatch):
        monkeypatch.setattr(pipeline_mod.time, "time", lambda: self.FIXED_NOW)

    def test_zero_or_negative_returns_now(self):
        assert pipeline_mod._validate_timestamp(0) == self.FIXED_NOW
        assert pipeline_mod._validate_timestamp(-1) == self.FIXED_NOW
        assert pipeline_mod._validate_timestamp(-1_000_000) == self.FIXED_NOW

    def test_future_beyond_one_day_returns_now(self):
        assert pipeline_mod._validate_timestamp(self.FIXED_NOW + 86401) == self.FIXED_NOW

    def test_exactly_one_day_future_kept(self):
        assert pipeline_mod._validate_timestamp(self.FIXED_NOW + 86400) == self.FIXED_NOW + 86400

    def test_before_year_2000_returns_now(self):
        assert pipeline_mod._validate_timestamp(self.EPOCH_2000 - 1) == self.FIXED_NOW

    def test_year_2000_boundary_kept(self):
        assert pipeline_mod._validate_timestamp(self.EPOCH_2000) == self.EPOCH_2000

    def test_valid_now_kept(self):
        assert pipeline_mod._validate_timestamp(self.FIXED_NOW) == self.FIXED_NOW
        assert pipeline_mod._validate_timestamp(self.FIXED_NOW - 100) == self.FIXED_NOW - 100

    def test_returns_int(self):
        assert isinstance(pipeline_mod._validate_timestamp(123), int)
        assert isinstance(pipeline_mod._validate_timestamp(0), int)
