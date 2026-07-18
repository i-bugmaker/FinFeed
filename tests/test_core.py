#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心功能测试"""

import unittest
import time
from unittest.mock import Mock, patch, MagicMock

from core.parsers.base import BaseParser, CATCH_UP_MAX_DAYS
from core.exceptions import (
    FinFeedError, FetchError, ParseError, StorageError,
    RateLimitError, CircuitOpenError, handle_http_error,
)
from storage.models import NewsItem
from config.sources import NewsSource


class TestParser(BaseParser):
    """测试用的 Parser 子类"""
    async def parse(self, response):
        return []


class TestBaseParser(unittest.TestCase):
    """测试 BaseParser 基类"""

    def setUp(self):
        self.source = NewsSource(
            name="test_source",
            url="http://test.com",
            method="GET",
            headers={},
            params={},
            parser_type="json",
            verify_ssl=True,
        )
        self.parser = TestParser(self.source)

    def test_get_catch_up_start_ts_no_last_ts(self):
        """测试没有上次时间戳时的补抓起始时间"""
        self.parser.last_ts = 0
        start_ts = self.parser.get_catch_up_start_ts()
        expected = int(time.time()) - CATCH_UP_MAX_DAYS * 24 * 3600
        self.assertAlmostEqual(start_ts, expected, delta=10)

    def test_get_catch_up_start_ts_with_last_ts(self):
        """测试有上次时间戳时的补抓起始时间"""
        recent_ts = int(time.time()) - 1000
        self.parser.last_ts = recent_ts
        start_ts = self.parser.get_catch_up_start_ts()
        self.assertEqual(start_ts, recent_ts)

    def test_get_catch_up_start_ts_last_ts_too_old(self):
        """测试上次时间戳超过7天时的补抓起始时间"""
        old_ts = int(time.time()) - 10 * 24 * 3600
        self.parser.last_ts = old_ts
        start_ts = self.parser.get_catch_up_start_ts()
        expected = int(time.time()) - CATCH_UP_MAX_DAYS * 24 * 3600
        self.assertAlmostEqual(start_ts, expected, delta=10)

    def test_is_newer_than_last(self):
        """测试时间戳比较"""
        self.parser.last_ts = 1000
        self.assertTrue(self.parser._is_newer_than_last(2000))
        self.assertFalse(self.parser._is_newer_than_last(500))
        self.assertFalse(self.parser._is_newer_than_last(1000))

    def test_update_last_ts(self):
        """测试更新最新时间戳"""
        news1 = NewsItem(title="news1", publish_ts=1000)
        news2 = NewsItem(title="news2", publish_ts=2000)
        news3 = NewsItem(title="news3", publish_ts=1500)

        self.parser.last_ts = 0
        self.parser.update_last_ts([news1, news2, news3])
        self.assertEqual(self.parser.last_ts, 2000)

    def test_make_news(self):
        """测试构造新闻对象"""
        news = self.parser._make_news(
            title="Test News Title",
            url="http://test.com/news",
            publish_ts=1620000000,
            intro="Test introduction",
        )
        self.assertEqual(news.title, "Test News Title")
        self.assertEqual(news.url, "http://test.com/news")
        self.assertEqual(news.publish_ts, 1620000000)
        self.assertEqual(news.intro, "Test introduction")

    def test_set_catch_up_mode(self):
        """测试设置补抓模式"""
        end_ts = 1620000000
        self.parser.set_catch_up_mode(True, end_ts)
        self.assertTrue(self.parser._catch_up_mode)
        self.assertEqual(self.parser._catch_up_end_ts, end_ts)

        self.parser.set_catch_up_mode(False)
        self.assertFalse(self.parser._catch_up_mode)


class TestExceptions(unittest.TestCase):
    """测试异常类"""

    def test_fetch_error(self):
        """测试 FetchError"""
        cause = ValueError("test")
        exc = FetchError("test_source", "test message", cause)
        self.assertEqual(exc.source_name, "test_source")
        self.assertEqual(exc.message, "test message")
        self.assertEqual(exc.cause, cause)
        self.assertIn("test_source", str(exc))
        self.assertIn("test message", str(exc))

    def test_parse_error(self):
        """测试 ParseError"""
        exc = ParseError("test_source", "parse failed")
        self.assertEqual(exc.source_name, "test_source")
        self.assertEqual(exc.message, "parse failed")

    def test_storage_error(self):
        """测试 StorageError"""
        exc = StorageError("db error")
        self.assertEqual(exc.message, "db error")

    def test_rate_limit_error(self):
        """测试 RateLimitError"""
        exc = RateLimitError("test_source", 30)
        self.assertEqual(exc.source_name, "test_source")
        self.assertEqual(exc.retry_after, 30)

    def test_circuit_open_error(self):
        """测试 CircuitOpenError"""
        exc = CircuitOpenError("test_source", 60)
        self.assertEqual(exc.source_name, "test_source")
        self.assertEqual(exc.remaining, 60)

    def test_handle_http_error_429(self):
        """测试 HTTP 429 处理"""
        exc = handle_http_error("test_source", 429, "30")
        self.assertIsInstance(exc, RateLimitError)
        self.assertEqual(exc.retry_after, 30)

    def test_handle_http_error_other(self):
        """测试其他HTTP错误处理"""
        with self.assertRaises(FetchError):
            handle_http_error("test_source", 500)


class TestNewsItem(unittest.TestCase):
    """测试新闻数据模型"""

    def test_news_item_creation(self):
        """测试新闻对象创建"""
        news = NewsItem(
            title="Test Title",
            url="http://test.com",
            source="Test Source",
            publish_time="2024-01-01 12:00:00",
            publish_ts=1704067200,
            intro="Test intro",
            keywords=["keyword1", "keyword2"],
            stocks=["600000"],
            sentiment="positive",
            importance=0.8,
        )
        self.assertEqual(news.title, "Test Title")
        self.assertEqual(news.url, "http://test.com")
        self.assertEqual(news.source, "Test Source")
        self.assertEqual(news.publish_time, "2024-01-01 12:00:00")
        self.assertEqual(news.publish_ts, 1704067200)
        self.assertEqual(news.intro, "Test intro")
        self.assertEqual(news.keywords, ["keyword1", "keyword2"])
        self.assertEqual(news.stocks, ["600000"])
        self.assertEqual(news.sentiment, "positive")
        self.assertEqual(news.importance, 0.8)

    def test_news_item_defaults(self):
        """测试新闻对象默认值"""
        news = NewsItem(title="Test")
        self.assertEqual(news.url, "#")
        self.assertEqual(news.source, "")
        self.assertEqual(news.publish_ts, 0)
        self.assertEqual(news.sentiment, "neutral")
        self.assertEqual(news.importance, 0.0)
        self.assertEqual(news.keywords, [])
        self.assertEqual(news.stocks, [])
        self.assertFalse(news.is_read)
        self.assertFalse(news.is_favorite)


if __name__ == "__main__":
    unittest.main()