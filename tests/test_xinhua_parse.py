#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：守护 xinhua.py 的 CNFIN_* 导入（对应 Bug 1 修复）。

若 xinhua.py 再次遗漏 `from .cnstock import CNFIN_*`，本模块的 import 阶段
就会因 NameError 失败，从而在 CI / 本地 `pytest` 中被立即拦截，避免信源静默失效。
"""
from finfeed.core.parsers.base import BaseParser
from finfeed.core.parsers.html_parsers import xinhua as xh


def test_cnfin_constants_imported():
    # Bug 1 根因：xinhua.py 引用了 cnstock.py 定义的 CNFIN_*，却未导入。
    # 若回归，这里会因 AttributeError / NameError 直接失败。
    assert hasattr(xh, "CNFIN_CHANNELS") and len(xh.CNFIN_CHANNELS) > 0
    assert hasattr(xh, "CNFIN_BASE_URL") and xh.CNFIN_BASE_URL.startswith("https://")
    assert hasattr(xh, "CNFIN_FLASH_API") and xh.CNFIN_FLASH_API.startswith("http")
    assert hasattr(xh, "CNFIN_FLASH_QUERY_IDS")


def test_parser_is_baseparser_subclass():
    assert issubclass(xh.XinhuaCaijingParser, BaseParser)


def test_parse_jsonp_valid():
    txt = 'jQuery123_456({"a": 1})'
    assert xh.XinhuaCaijingParser._parse_jsonp(txt) == {"a": 1}


def test_parse_jsonp_plain_json():
    assert xh.XinhuaCaijingParser._parse_jsonp('{"b": 2}') == {"b": 2}


def test_parse_jsonp_invalid_returns_none():
    assert xh.XinhuaCaijingParser._parse_jsonp("not json <<<") is None
