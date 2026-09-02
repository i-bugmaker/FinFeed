#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法布财经（电报式快讯源）入库与正文回归测试（临时库 + 不发真实请求）。

线上问题（2026-07-30 起）：法布财经除 1 条外全部静默丢失。根因是
idx_url_source 唯一索引建在 (url, source) 全量上，而法布快讯无详情页、
url 一律为哨兵值 "#"，于是 ("#", "法布财经") 组合只能存在一条，
其后所有条目被 INSERT OR IGNORE 悄悄丢弃。
"""
import asyncio
import json

import httpx
import pytest

import finfeed.storage.database as db_mod
from finfeed.config.flash_sources import get_flash_sources
from finfeed.core.parsers.html_parsers.fastbull import FastbullParser


def _run(coro):
    return asyncio.run(coro)


def _api_payload(items: list[dict]) -> httpx.Response:
    """构造与 getNewsPageByTagIds 一致的响应（bodyMessage 为内嵌 JSON 字符串）"""
    body = json.dumps({"pageDatas": items}, ensure_ascii=False)
    return httpx.Response(200, json={"code": 0, "bodyMessage": body})


def _flash_item(title: str, ts_ms: int = 1788275113149) -> dict:
    return {
        "newsId": "4255299_212_1",
        "path": "4255299_212_1",
        "newsTitle": title,
        "newsType": 0,
        "hasOfficialDetail": 0,
        "releasedDate": ts_ms,
        "newsUnscrambleModel": None,
        "refInfo": None,
        "simWebsiteName": None,
    }


@pytest.fixture()
def fastbull_source():
    return [s for s in get_flash_sources() if s.name == "法布财经"][0]


def test_fastbull_content_is_full_text(fastbull_source):
    """电报式快讯标题即全文：content 应携带完整文本（不受 80 字标题截断影响）"""
    long_title = "英国央行曼恩：" + "利率路径取决于经济数据的表现，" * 6 + "必要时将果断行动。"
    parser = FastbullParser(fastbull_source)
    items = _run(parser.parse(_api_payload([_flash_item(long_title)])))
    assert len(items) == 1
    assert items[0].url == "#"
    assert len(items[0].title) <= 80          # 标题仍按惯例截断
    assert items[0].content == long_title     # 正文保留全文


def test_fastbull_intro_from_unscramble(fastbull_source):
    """携带 newsUnscrambleModel 的条目应拆出 intro 摘要"""
    item = _flash_item("美联储纪要：内部对降息节奏存在分歧。")
    item["newsUnscrambleModel"] = {"content": "纪要显示多数委员支持观望立场。"}
    parser = FastbullParser(fastbull_source)
    items = _run(parser.parse(_api_payload([item])))
    assert items[0].intro == "纪要显示多数委员支持观望立场。"


def test_url_sentinel_does_not_block_insert(tmp_path, monkeypatch):
    """同来源多条 url='#' 条目必须都能入库（哨兵值不参与 URL 查重）"""
    import sqlite3

    monkeypatch.setattr(db_mod, "DB_PATH", str(tmp_path / "test_news.db"))
    db_mod._global_db = None
    db_mod.init_db()

    from finfeed.storage.models import NewsItem

    def _item(title: str, h: str) -> NewsItem:
        return NewsItem(title=title, url="#", source="法布财经",
                        title_hash=h, content=title)

    n1 = _item("快讯甲：内容一。", "hash-a")
    n2 = _item("快讯乙：内容二。", "hash-b")
    _, count = db_mod.db_insert_news([n1, n2])
    assert count == 2, "url='#' 的多条同源条目不应被唯一索引拦截"

    # 相同 title_hash 的重复仍应被去重
    _, count2 = db_mod.db_insert_news([_item("快讯甲：内容一。", "hash-a")])
    assert count2 == 0

    # 库内索引应为部分唯一索引（排除哨兵值）
    with sqlite3.connect(db_mod.DB_PATH) as c:
        sql = c.execute(
            "SELECT sql FROM sqlite_master WHERE name='idx_url_source'"
        ).fetchone()[0]
        assert "WHERE" in sql.upper(), "idx_url_source 必须排除 url='#' 哨兵行"
